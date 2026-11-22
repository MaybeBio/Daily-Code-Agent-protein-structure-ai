import os
import argparse
import torch
import pandas as pd
import numpy as np
from torch.utils.data import DataLoader
from torchvision import transforms
import joblib
from tqdm import tqdm  # === 新增：进度条 ===
import chardet

# === 依赖你现有的 mode.py ===
from mode import TeacherModel, TeacherDataset, DEVICE, IMG_SIZE


####################################################################
# 1. 增强数据集：返回所有必要信息
####################################################################

class Mode4FullDataset(TeacherDataset):
    """返回所有模态数据及元信息，用于知识提取"""

    def __getitem__(self, idx):
        # 调用父类获取基础数据
        img_c, img_l, struct, y = super().__getitem__(idx)

        return {
            "img_complex": img_c,
            "img_ligand": img_l,
            "struct": struct,
            "filename": self.filenames[idx],
            "smiles": self.smiles[idx] if hasattr(self, "smiles") else "",
            "affinity": self.orig_aff[idx]  # 原始亲和力值
        }


####################################################################
# 2. 提取多类型知识
####################################################################

def extract_knowledge(model: TeacherModel, loader: DataLoader, out_path: str, label_scaler):
    """提取教师模型的多类型知识并保存"""
    model.eval()
    knowledge = {
        "filenames": [],
        "smiles": [],
        "ligand_vec": [],  # 对齐后的配体表示 (256-D)
        "pocket_vec": [],  # 蛋白质口袋表示 (256-D)
        "attentions": [],  # 多层注意力图
        "pred_affinity": [],  # 预测的亲和力值
        "true_affinity": []  # 真实亲和力值
    }

    # === 新增：使用 tqdm 包装 loader 显示进度 ===
    with torch.no_grad():
        for batch in tqdm(loader, desc="提取教师知识", unit="batch"):
            # 准备输入数据
            img_c = batch["img_complex"].to(DEVICE)
            img_l = batch["img_ligand"].to(DEVICE)
            struct = batch["struct"].to(DEVICE)

            # 获取教师模型输出 (包含中间特征)
            teacher_out = model(
                img_c,
                struct,
                img_ligand=img_l,
                return_feats=True
            )

            # 收集知识
            knowledge["filenames"].extend(batch["filename"])
            knowledge["smiles"].extend(batch["smiles"])
            knowledge["true_affinity"].extend(batch["affinity"].numpy())
            raw_pred = teacher_out["pred"].cpu().numpy().reshape(-1, 1)
            pred_inv = label_scaler.inverse_transform(raw_pred).squeeze()
            
            # 确保 pred_inv 即使是单样本也是一维列表
            if pred_inv.ndim == 0:
                knowledge["pred_affinity"].append(float(pred_inv))
            else:
                knowledge["pred_affinity"].extend(pred_inv.tolist())
                
            # === 修改：强制转换为 float16 节省 50% 内存 ===
            knowledge["ligand_vec"].append(teacher_out["ligand_rep"].cpu().numpy().astype(np.float16))
            knowledge["pocket_vec"].append(teacher_out["pocket_rep"].cpu().numpy().astype(np.float16))

            # 处理注意力图
            B = raw_pred.shape[0]
            layer_list = teacher_out["attn_maps"]  

            # 按样本拆分，再把每层矩阵存成 list
            for b in range(B):
                # === 修改：强制转换为 float16 节省海量内存 ===
                sample_layers = [lay[b].cpu().numpy().astype(np.float16) for lay in layer_list]  
                knowledge["attentions"].append(sample_layers)

    # 合并批次数据
    knowledge["pred_affinity"] = np.array(knowledge["pred_affinity"])
    for key in ["ligand_vec", "pocket_vec"]:
        knowledge[key] = np.concatenate(knowledge[key], axis=0)

    print(f"\n正在将数据打包并写入 {out_path}，请耐心等待（文件可能较大）...")
    
    # 转换为DataFrame保存
    df = pd.DataFrame({
        "Filename": knowledge["filenames"],
        "SMILES": knowledge["smiles"],
        "TrueAffinity": knowledge["true_affinity"],
        "PredAffinity": knowledge["pred_affinity"],
        "LigandVector": list(knowledge["ligand_vec"]),
        "PocketVector": list(knowledge["pocket_vec"]),
        "AttentionMaps": list(knowledge["attentions"])  
    })

    df.to_pickle(out_path)
    print(f"✅ 成功！已保存 {len(df)} 条知识记录 → {out_path}")
    print("知识内容概览:")
    print(f"- 配体向量维度: {knowledge['ligand_vec'].shape[1]} (float16)")
    print(f"- 口袋向量维度: {knowledge['pocket_vec'].shape[1]} (float16)")
    print(f"- 注意力图层数: {len(knowledge['attentions'][0])}")
    print(f"- 单层矩阵尺寸示例: {knowledge['attentions'][0][0].shape} (float16)")  


####################################################################
# 3. 主函数
####################################################################

def main():
    parser = argparse.ArgumentParser(
        description="从mode4教师模型提取跨模态知识")
    parser.add_argument("--teacher_ckpt", required=True, help="教师模型路径 teacher_model_mode4.pth")
    parser.add_argument("--data_csv", default="./merger_aff.csv")
    parser.add_argument("--struct_csv", default="./merger_str.csv")
    parser.add_argument("--batch", type=int, default=16) # 推理不保存梯度，16应该不会OOM
    parser.add_argument("--out", default="teacher_knowledge.pkl")
    parser.add_argument("--scaler", default="label_scaler.pkl")
    args = parser.parse_args()
    
    label_scaler = joblib.load(args.scaler)

    # 数据集
    tf = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    def detect_encoding(file_path):
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read())
        return result['encoding']

    data_encoding = detect_encoding(args.data_csv)
    struct_encoding = detect_encoding(args.struct_csv)

    main_df = pd.read_csv(args.data_csv, encoding=data_encoding)
    struct_df = pd.read_csv(args.struct_csv, encoding=struct_encoding)

    print("正在初始化数据集并计算结构特征...")
    # 创建数据集 (不缩放标签)
    dataset = Mode4FullDataset(
        main_df, struct_df,
        mode="mode4",
        transform=tf,
        scale_label=False
    )

    loader = DataLoader(
        dataset,
        batch_size=args.batch,
        shuffle=False,
        num_workers=4,
        collate_fn=lambda batch: {  
            "img_complex": torch.stack([x["img_complex"] for x in batch]),
            "img_ligand": torch.stack([x["img_ligand"] for x in batch]),
            "struct": torch.stack([x["struct"] for x in batch]),
            "filename": [x["filename"] for x in batch],
            "smiles": [x["smiles"] for x in batch],
            "affinity": torch.tensor([x["affinity"] for x in batch])
        }
    )

    # 加载教师模型
    struct_dim = dataset.struct_feats.shape[1]
    teacher = TeacherModel(struct_dim=struct_dim, mode="mode4").to(DEVICE)

    state = torch.load(args.teacher_ckpt, map_location=DEVICE)
    if list(state.keys())[0].startswith("module."):
        state = {k.replace("module.", "", 1): v for k, v in state.items()}

    teacher.load_state_dict(state, strict=True)
    print(f"✅ 教师模型加载成功: {args.teacher_ckpt}")

    # 提取知识
    extract_knowledge(teacher, loader, args.out, label_scaler)


if __name__ == "__main__":
    main()