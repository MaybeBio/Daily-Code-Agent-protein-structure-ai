#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from multiprocessing import freeze_support
import torch.multiprocessing as tmp
from ultralytics import YOLO
from pathlib import Path
import numpy as np


def train(
        data: str,
        model: str = 'yolov8m.pt',
        epochs: int = 200,
        imgsz: int = 1920,
        batch: int = 4,
        lr0: float = 0.01,
        amp: bool = True,
        patience: int = 30,
        resume: str = None,
) -> YOLO:
    """存在性检测专用训练函数"""
    model = YOLO(resume if resume and Path(resume).exists() else model)

    results = model.train(
        data=data,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        lr0=lr0,
        amp=amp,
        workers=0,
        patience=patience,
        verbose=False,
        iou=0.5,
        rect=False,
        degrees=0,
        translate=0,
        scale=0,
        fliplr=0.5,
        mask_ratio=4,
    )

    best_model = Path(model.trainer.best).absolute()
    print(f"\n训练完成! 最佳模型路径: {best_model}")
    return YOLO(best_model)


if __name__ == "__main__":
    freeze_support()
    tmp.set_sharing_strategy('file_system')

    # 配置路径
    DATA_YAML = './datasets/amino_yolo/data.yaml'

    # —— 训练阶段 ——
    detector = train(
        data=DATA_YAML,
        model='yolov8m.pt',
        epochs=300,
        batch=4,
        lr0=3e-4,
        patience=30,
    )