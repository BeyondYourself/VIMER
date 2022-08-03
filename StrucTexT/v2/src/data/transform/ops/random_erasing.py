""" random_erasing """
# Copyright (c) 2021 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#This code is adapted from https://github.com/zhunzhong07/Random-Erasing, and refer to Timm.

from functools import partial

import math
import random
import numpy as np

__all__ = ['RandomErasing']

class Pixels(object):
    """ Pixels """
    def __init__(self, mode="const", mean=[0., 0., 0.]):
        self._mode = mode
        self._mean = mean

    def __call__(self, h=224, w=224, c=3):
        if self._mode == "rand":
            return np.random.normal(size=(1, 1, 3))
        elif self._mode == "pixel":
            return np.random.normal(size=(h, w, c))
        elif self._mode == "const":
            return self._mean
        else:
            raise Exception(
                "Invalid mode in RandomErasing, only support \"const\", \"rand\", \"pixel\""
            )


class RandomErasing(object):
    """RandomErasing.
    """

    def __init__(self,
                 EPSILON=0.5,
                 sl=0.02,
                 sh=0.4,
                 r1=0.3,
                 mean=[0., 0., 0.],
                 attempt=100,
                 use_log_aspect=False,
                 mode='const'):
        self.EPSILON = eval(EPSILON) if isinstance(EPSILON, str) else EPSILON
        self.sl = eval(sl) if isinstance(sl, str) else sl
        self.sh = eval(sh) if isinstance(sh, str) else sh
        r1 = eval(r1) if isinstance(r1, str) else r1
        self.r1 = (math.log(r1), math.log(1 / r1)) if use_log_aspect else (
            r1, 1 / r1)
        self.use_log_aspect = use_log_aspect
        self.attempt = attempt
        self.get_pixels = Pixels(mode, mean)

    def __call__(self, data):
        if random.random() > self.EPSILON:
            return data

        img = data['image']
        channel_first = False
        if img.ndim == 3 and img.shape[0] == 3:
            channel_first = True
            img = np.transpose(img, (1, 2, 0))

        for _ in range(self.attempt):
            area = img.shape[0] * img.shape[1]

            target_area = random.uniform(self.sl, self.sh) * area
            aspect_ratio = random.uniform(*self.r1)
            if self.use_log_aspect:
                aspect_ratio = math.exp(aspect_ratio)

            h = int(round(math.sqrt(target_area * aspect_ratio)))
            w = int(round(math.sqrt(target_area / aspect_ratio)))

            if w < img.shape[1] and h < img.shape[0]:
                pixels = self.get_pixels(h, w, img.shape[2])
                x1 = random.randint(0, img.shape[0] - h)
                y1 = random.randint(0, img.shape[1] - w)
                img[x1:x1 + h, y1:y1 + w] = pixels
                break
        data['image'] = np.transpose(img, (2, 0, 1)) if channel_first else img
        return data
