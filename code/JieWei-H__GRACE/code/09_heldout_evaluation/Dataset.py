import json
import random
import re

import pandas as pd
import numpy as np
from torch.utils.data import Dataset, DataLoader
import torch
from sklearn.model_selection import train_test_split
import os
import ast

os.environ["TOKENIZERS_PARALLELISM"] = "false"


class PretrainDataset(Dataset):
    def __init__(self, data_path, tokenizer, max_length=512):
        super().__init__()
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = self.load_data(data_path)
        self.pad_token_id = tokenizer.vocab["[PAD]"]  # 获取填充标记ID

    def load_data(self, path):
        """加载JSON格式的预训练数据"""
        try:
            # 整个文件是一个JSON数组
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except json.JSONDecodeError as e:
            print(f"加载数据错误: {str(e)}")
            return []
        except Exception as e:
            print(f"文件读取错误: {str(e)}")
            return []

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        sample = self.samples[index]
        text = sample['text']  # 获取基因序列文本
        
        # 使用自定义tokenizer编码基因序列
        input_ids = self.tokenizer.encode(text, self.max_length)
        
        # 创建输入序列 (X) 和标签序列 (Y)
        # X: [BOS, token1, token2, ..., tokenN]
        # Y: [token1, token2, ..., tokenN, EOS]
        X = input_ids[:-1]  # 移除最后一个token作为输入
        Y = input_ids[1:]   # 移除第一个token作为标签
        
        # 创建损失掩码 - 只计算非填充位置的损失
        # 注意: 我们只关心真实序列部分的损失，忽略填充部分
        loss_mask = [1 if token != self.pad_token_id else 0 for token in X]
        
        # 确保所有序列长度一致
        if len(X) < self.max_length:
            # 填充输入序列
            X += [self.pad_token_id] * (self.max_length - len(X))
            # 填充标签序列
            Y += [self.pad_token_id] * (self.max_length - len(Y))
            # 填充损失掩码
            loss_mask += [0] * (self.max_length - len(loss_mask))
        else:
            # 截断到最大长度
            X = X[:self.max_length]
            Y = Y[:self.max_length]
            loss_mask = loss_mask[:self.max_length]
        
        # 转换为PyTorch张量
        X_tensor = torch.tensor(X, dtype=torch.long)
        Y_tensor = torch.tensor(Y, dtype=torch.long)
        loss_mask_tensor = torch.tensor(loss_mask, dtype=torch.float)
        
        
        # 添加数据检查
        if torch.isnan(X_tensor).any() or torch.isnan(Y_tensor).any():
            print(f"发现NaN值在样本 {index}")
            return self[(index + 1) % len(self)]  # 跳过问题样本
        
        # 检查损失掩码是否合理
        if loss_mask_tensor.sum() == 0:
            print(f"空损失掩码在样本 {index}")
            return self[(index + 1) % len(self)]
        
        
        return X_tensor, Y_tensor, loss_mask_tensor

class SFTDataset(Dataset):
    def __init__(self, jsonl_path, tokenizer, max_length=512):
        super().__init__()
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = self.load_data(jsonl_path)
        
        # 使用 tokenizer 中的特殊 token ID
        self.bos_id = tokenizer.bos_id  # <|im_start|>
        self.eos_id = tokenizer.eos_id  # <|im_end|>
        self.pad_id = tokenizer.pad_id  # [PAD]
        self.user_id = tokenizer.user_id  # <|user|> 
        self.assistant_id = tokenizer.assistant_id  # <|assistant|> 
    
    def __len__(self):
        return len(self.samples)

    def load_data(self, path):
        """加载对话格式的数据（每行一个JSON对象）"""
        samples = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if 'conversations' in item:
                    samples.append(item)
        return samples

    def _create_chat_prompt(self, conversations):
        """使用新的特殊token构建对话格式"""
        formatted = []
        for turn in conversations:
            if turn['role'] == 'user':
                # 用户消息格式: <|im_start|><|user|>内容<|im_end|>
                formatted.append(f"<|im_start|><|user|>{turn['content'].strip()}")
            else:
                # 助手消息格式: <|im_start|><|assistant|>内容<|im_end|>
                formatted.append(f"<|assistant|>{turn['content'].strip()}<|im_end|>")
        return "".join(formatted)

    def _generate_loss_mask(self, input_ids):
        """生成只计算助手回复的loss掩码（基于新的token格式）"""
        loss_mask = [0] * len(input_ids)
        in_assistant_response = False

        for i in range(len(input_ids)):
            # 检查是否进入助手回复
            if i < len(input_ids) and input_ids[i] == self.assistant_id:
                in_assistant_response = True
                # 注意：这里不设置损失掩码，因为我们要跳过<|im_start|>和<|assistant|>
                continue

            # 检查是否退出助手回复
            if in_assistant_response and input_ids[i] == self.eos_id:
                # 助手回复的结束标记也计算损失
                loss_mask[i] = 1
                in_assistant_response = False
                continue

            # 如果在助手回复中，计算损失
            if in_assistant_response:
                loss_mask[i] = 1

        return loss_mask
  
    # def _generate_loss_mask(self, input_ids):
    #     """生成只计算助手回复的loss掩码（基于新的token格式）"""
    #     loss_mask = [0] * len(input_ids)
    #     in_assistant_response = False
    #     
    #     for i in range(len(input_ids)):
    #         # 检查是否进入助手回复
    #         if i < len(input_ids) and input_ids[i] == self.bos_id:
    #             in_assistant_response = True
    #             # 注意：这里不设置损失掩码，因为我们要跳过<|im_start|>和<|assistant|>
    #             continue
    #         
    #         # 检查是否退出助手回复
    #         if in_assistant_response and input_ids[i] == self.eos_id:
    #             # 助手回复的结束标记也计算损失
    #             loss_mask[i] = 1
    #             in_assistant_response = False
    #             continue
    #         
    #         # 如果在助手回复中，计算损失
    #         if in_assistant_response:
    #             loss_mask[i] = 1
    #     
    #     return loss_mask
  
    def __getitem__(self, index):
        sample = self.samples[index]
        
        # 构建对话提示
        prompt = self._create_chat_prompt(sample['conversations'])
        
        # 使用自定义tokenizer编码
        input_ids = self.tokenizer.encode(prompt, self.max_length)
        
        # 生成动态损失掩码（只计算助手回复部分）
        loss_mask = self._generate_loss_mask(input_ids)
        
        # 确保长度一致
        if len(input_ids) < self.max_length:
            pad_length = self.max_length - len(input_ids)
            input_ids += [self.pad_id] * pad_length
            loss_mask += [0] * pad_length
        else:
            input_ids = input_ids[:self.max_length]
            loss_mask = loss_mask[:self.max_length]
        
        # 构建训练数据 (X: 输入, Y: 目标)
        X = input_ids[:-1]  # 移除最后一个token作为输入
        Y = input_ids[1:]   # 移除第一个token作为标签
        loss_mask = loss_mask[1:]  # 对齐Y的长度
        
        # 转换为PyTorch张量
        X_tensor = torch.tensor(X, dtype=torch.long)
        Y_tensor = torch.tensor(Y, dtype=torch.long)
        loss_mask_tensor = torch.tensor(loss_mask, dtype=torch.float)
        
        # 数据检查
        if torch.isnan(X_tensor).any() or torch.isnan(Y_tensor).any():
            print(f"发现NaN值在SFT样本 {index}")
            return self[(index + 1) % len(self)]
        
        return X_tensor, Y_tensor, loss_mask_tensor

if __name__ == "__main__":
    pass
