#!/usr/bin/env python

import os
import cv2
from ultralytics import YOLO
from collections import defaultdict
from pathlib import Path
import pandas as pd

# ======== 配置超参数 =========
MODEL_PATH = './runs/detect/train45/weights/best.pt'
SOURCE = './pngift'
CONFIDENCE = 0.5
IMG_SIZE = 1536  
OUTPUT_CSV = './merger_str.csv'   
OUTPUT_IMG_DIR = './predicted_images'
BATCH_SIZE = 16  # 充分利用L20显存批量处理
# ==============================

class Predictor:
    CLASS_NAMES = [
        'Ala', 'Arg', 'Asn', 'Asp', 'Cys', 'Gln', 'Glu', 'Gly', 'His', 'Ile',
        'Leu', 'Lys', 'Met', 'Phe', 'Pro', 'Ser', 'Thr', 'Trp', 'Tyr', 'Val',
        'H', 'BH', 'NB', 'SH'
    ]

    def __init__(self, model_path: str):
        try:
            self.model = YOLO(model_path)
            self.model.fuse()
            print(f"模型加载成功: {model_path}")
        except Exception as e:
            print(f"模型加载失败: {e}")
            raise

    def predict_adaptive(self, source, target_size=1280, confidence=0.5):
        """
        利用 L20 GPU 性能的高效预测
        """
        try:
            results = self.model.predict(
                source=source,
                imgsz=target_size,
                conf=confidence,
                iou=0.7,
                rect=True,
                augment=False,
                verbose=False,
                stream=True,  
                batch=BATCH_SIZE, 
                half=True,        
                device=0          
            )
            return results  
        except Exception as e:
            print(f"预测过程中出错: {e}")
            return []

    def process_results_incremental(self, results_generator, output_dir: str = OUTPUT_IMG_DIR):
        """
        增量处理结果，避免在内存中保存所有结果
        """
        os.makedirs(output_dir, exist_ok=True)
        stats = {}
        processed_count = 0

        for result in results_generator:
            try:
                img_key = str(result.path)
                print(f"处理图像: {Path(img_key).name}")

                # 分析单张图像的结果
                img_stats = self.analyze_single_result(result)
                stats[img_key] = img_stats

                # 保存单张标注图像
                self.save_single_annotated_image(result, output_dir)

                processed_count += 1

            except Exception as e:
                print(f"处理图像 {result.path} 时出错: {e}")
                continue

        print(f"成功处理 {processed_count} 张图像")
        return stats

    def analyze_single_result(self, result):
        """分析单张图像的结果"""
        img_stats = {
            'amino': defaultdict(int),
            'h_bonds': defaultdict(int)
        }

        if result.boxes is not None:
            for box in result.boxes:
                cls_id = int(box.cls)
                cls_name = self.CLASS_NAMES[cls_id]
                img_stats['amino'][cls_name] += 1

            # 统计氢键
            img_stats['h_bonds']['H'] = sum(1 for b in result.boxes if int(b.cls) == 20)
            img_stats['h_bonds']['BH'] = sum(1 for b in result.boxes if int(b.cls) == 21)
            img_stats['h_bonds']['NB'] = sum(1 for b in result.boxes if int(b.cls) == 22)
            img_stats['h_bonds']['SH'] = sum(1 for b in result.boxes if int(b.cls) == 23)

        return img_stats

    def save_single_annotated_image(self, result, output_dir: str):
        """保存单张标注图像"""
        try:
            annotated = result.plot()
            img_name = Path(result.path).name
            save_path = Path(output_dir) / img_name
            cv2.imwrite(str(save_path), annotated)
        except Exception as e:
            print(f"保存标注图像 {result.path} 时出错: {e}")

    def print_stats(self, stats):
        for img_path, data in stats.items():
            print(f"\n检测结果: {Path(img_path).name}")
            print("氨基酸统计:")
            for name, count in data['amino'].items():
                print(f"  {name}: {count}")

            print("\n氢键统计:")
            print(f"  强氢键 (H): {data['h_bonds']['H']}")
            print(f"  弱氢键 (BH): {data['h_bonds']['BH']}")
            print(f"  弱氢键 (NB): {data['h_bonds']['NB']}")
            print(f"  弱氢键 (SH): {data['h_bonds']['SH']}")
            print("-" * 40)

    def save_stats_csv_sorted(self, stats, csv_path: str = OUTPUT_CSV):
        """【新增核心功能】将结果转为DataFrame，按数字排序后直接保存为CSV"""
        try:
            data_rows = []
            for img, d in stats.items():
                # 将列名统一改为 Filename，与你的 sort_csv.py 保持一致
                row = {'Filename': Path(img).name}
                for name in self.CLASS_NAMES:
                    row[name] = d['amino'].get(name, 0)
                row['H'] = d['h_bonds'].get('H', 0)
                row['BH'] = d['h_bonds'].get('BH', 0)
                row['NB'] = d['h_bonds'].get('NB', 0)
                row['SH'] = d['h_bonds'].get('SH', 0)
                data_rows.append(row)
            
            # 1. 转换为 DataFrame
            df = pd.DataFrame(data_rows)
            
            # 2. 从文件名中提取数字作为排序键 (使用 fillna(0) 防止有没有数字的异常文件名报错)
            df['__sort_key__'] = (
                df['Filename']
                .str.extract(r'(\d+)', expand=False)
                .fillna(0)
                .astype(int)
            )
            
            # 3. 按提取的数字排序，并删除辅助列
            df_sorted = df.sort_values('__sort_key__', kind='stable').drop(columns='__sort_key__')
            
            # 4. 直接保存为 UTF-8 编码的 CSV 文件
            df_sorted.to_csv(csv_path, index=False, encoding='utf-8')
            print(f"\n结果已按数字顺序排序，并成功保存到 CSV 文件: {csv_path}")
            
        except Exception as e:
            print(f"保存CSV文件时出错: {e}")


if __name__ == '__main__':
    try:
        predictor = Predictor(MODEL_PATH)

        print("开始预测（使用增量处理减少内存使用）...")
        results_generator = predictor.predict_adaptive(
            source=SOURCE,
            target_size=IMG_SIZE,
            confidence=CONFIDENCE
        )

        # 增量处理结果
        stats = predictor.process_results_incremental(results_generator, OUTPUT_IMG_DIR)

        if not stats:
            print("没有获得任何预测结果，请检查输入源和模型路径")
            exit(1)

        # predictor.print_stats(stats)  # 如果终端输出太多，可以把这行注释掉
        
        # 调用新的排序与CSV导出函数
        predictor.save_stats_csv_sorted(stats, OUTPUT_CSV)

        print("所有任务完成!")

    except Exception as e:
        print(f"程序执行过程中出错: {e}")