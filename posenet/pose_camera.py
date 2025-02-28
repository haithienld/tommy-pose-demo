# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import collections
from functools import partial
import re
import time

import numpy as np
from PIL import Image
import svgwrite
import gstreamer
import os

from pose_engine import PoseEngine

EDGES = (
    ('nose', 'left eye'),
    ('nose', 'right eye'),
    ('nose', 'left ear'),
    ('nose', 'right ear'),
    ('left ear', 'left eye'),
    ('right ear', 'right eye'),
    ('left eye', 'right eye'),
    ('left shoulder', 'right shoulder'),
    ('left shoulder', 'left elbow'),
    ('left shoulder', 'left hip'),
    ('right shoulder', 'right elbow'),
    ('right shoulder', 'right hip'),
    ('left elbow', 'left wrist'),
    ('right elbow', 'right wrist'),
    ('left hip', 'right hip'),
    ('left hip', 'left knee'),
    ('right hip', 'right knee'),
    ('left knee', 'left ankle'),
    ('right knee', 'right ankle'),
)


def shadow_text(dwg, x, y, text, font_size=16):
    dwg.add(dwg.text(text, insert=(x + 1, y + 1), fill='black',
                     font_size=font_size, style='font-family:sans-serif'))
    dwg.add(dwg.text(text, insert=(x, y), fill='white',
                     font_size=font_size, style='font-family:sans-serif'))


def draw_pose(dwg, pose, src_size, inference_box, color='yellow', threshold=0.2):
    print('inf box', inference_box)
    box_x, box_y, box_w, box_h = inference_box
    scale_x, scale_y = src_size[0] / box_w, src_size[1] / box_h
    xys = {}
    for label, keypoint in pose.keypoints.items():
        if keypoint.score < threshold: continue
        # Offset and scale to source coordinate space.
        kp_y = int((keypoint.yx[0] - box_y) * scale_y)
        kp_x = int((keypoint.yx[1] - box_x) * scale_x)

        xys[label] = (kp_x, kp_y)
        dwg.add(dwg.circle(center=(int(kp_x), int(kp_y)), r=5,
                           fill='cyan', fill_opacity=keypoint.score, stroke=color))

    for a, b in EDGES:
        if a not in xys or b not in xys: continue
        ax, ay = xys[a]
        bx, by = xys[b]
        dwg.add(dwg.line(start=(ax, ay), end=(bx, by), stroke=color, stroke_width=2))

def avg_fps_counter(window_size):
    window = collections.deque(maxlen=window_size)
    prev = time.monotonic()
    yield 0.0  # First fps value.

    while True:
        curr = time.monotonic()
        window.append(curr - prev)
        prev = curr
        yield len(window) / sum(window)

def run(inf_callback, render_callback):
    default_model_dir = '../all_models'
    default_model = 'posenet/posenet_mobilenet_v1_075_481_641_quant_decoder_edgetpu.tflite'
    default_labels = 'hand_label.txt'
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help='.tflite model path',
                        default=os.path.join(default_model_dir,default_model))
    parser.add_argument('--mirror', help='flip video horizontally', action='store_true')
    parser.add_argument('--labels', help='label file path',
                        default=os.path.join(default_model_dir, default_labels))
    parser.add_argument('--top_k', type=int, default=1,
                        help='number of categories with highest score to display')
    parser.add_argument('--camera_idx', type=str, help='Index of which video source to use. ', default = 0)
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='classifier score threshold')
    parser.add_argument('--videosrc', help='Which video source to use', default='/dev/video0')
    parser.add_argument('--h264', help='Use video/x-h264 input', action='store_true')
    parser.add_argument('--jpeg', help='Use image/jpeg input', action='store_true')
    args = parser.parse_args()
    src_size = (640, 480)
    engine = PoseEngine(args.model)
    input_shape = engine.get_input_tensor_shape()
    inference_size = (input_shape[2], input_shape[1])

    gstreamer.run_pipeline(partial(inf_callback, engine), partial(render_callback, engine),
                           src_size, inference_size,
                           mirror=args.mirror,
                           videosrc=args.videosrc,
                           h264=args.h264,
                           jpeg=args.jpeg
                           )


def main():
    n = 0
    sum_process_time = 0
    sum_inference_time = 0
    ctr = 0
    fps_counter  = avg_fps_counter(30)

    def run_inference(engine, input_tensor):
        return engine.run_inference(input_tensor)

    def render_overlay(engine, output, src_size, inference_box):
        nonlocal n, sum_process_time, sum_inference_time, fps_counter

        svg_canvas = svgwrite.Drawing('', size=src_size)
        start_time = time.monotonic()
        outputs, inference_time = engine.ParseOutput(output)
        end_time = time.monotonic()
        n += 1
        sum_process_time += 1000 * (end_time - start_time)
        sum_inference_time += inference_time

        avg_inference_time = sum_inference_time / n
        text_line = 'PoseNet: %.1fms (%.2f fps) TrueFPS: %.2f Nposes %d' % (
            avg_inference_time, 1000 / avg_inference_time, next(fps_counter), len(outputs)
        )

        shadow_text(svg_canvas, 10, 20, text_line)
        for pose in outputs:
            draw_pose(svg_canvas, pose, src_size, inference_box)
        return (svg_canvas.tostring(), False)

    run(run_inference, render_overlay)


if __name__ == '__main__':
    main()
