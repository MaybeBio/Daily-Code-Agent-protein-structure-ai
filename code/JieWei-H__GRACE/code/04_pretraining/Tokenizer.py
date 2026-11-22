import os
import json
import re
from collections import OrderedDict
import pickle
import torch

def build_gene_tokenizer(gene_list, save_path='../Token/'):
    # 1. 扩展特殊token定义，添加用户和助手标记
    special_tokens = OrderedDict([
        ("[PAD]", 0),
        ("<|im_start|>", 1),     # 对话开始标记
        ("<|im_end|>", 2),       # 对话结束标记
        ("[UNK]", 3),            # 未知标记
        ("<|user|>", 4),         # 新增：用户角色标记
        ("<|assistant|>", 5)     # 新增：助手角色标记
    ])
    
    # 2. 使用传入的基因列表（已排序）
    all_genes = sorted(set(str(gene) for gene in gene_list))
    
    # 3. 构建完整词汇表，从6开始编号（因为有6个特殊token）
    vocab = special_tokens.copy()
    for idx, gene in enumerate(all_genes, start=len(special_tokens)):
        vocab[gene] = idx
    
    # 4. 创建保存目录
    os.makedirs(save_path, exist_ok=True)
    
    # 5. 保存词汇表文件
    with open(os.path.join(save_path, 'vocab.json'), 'w') as f:
        json.dump(vocab, f, indent=2)
    
    # 6. 保存tokenizer配置
    tokenizer_config = {
        "model_max_length": 200,
        "padding_side": "left",
        "bos_token": "<|im_start|>",      # 开始标记
        "eos_token": "<|im_end|>",        # 结束标记
        "unk_token": "[UNK]",
        "pad_token": "[PAD]",
        "additional_special_tokens": ["<|user|>", "<|assistant|>"]  # 新增
    }
    with open(os.path.join(save_path, 'tokenizer_config.json'), 'w') as f:
        json.dump(tokenizer_config, f, indent=2)
    
    print(f"Tokenizer构建完成，词汇表大小: {len(vocab)}")
    print(f"特殊token: {list(special_tokens.keys())}")
    return vocab

class GeneTokenizer:
    def __init__(self, vocab_path='./Token/vocab.json'):
        with open(vocab_path, 'r') as f:
            self.vocab = json.load(f)
            # 确保ID转换为整数
            self.id2token = {int(id_): token for token, id_ in self.vocab.items()}
        
        config_path = os.path.join(os.path.dirname(vocab_path), 'tokenizer_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.padding_side = config.get('padding_side', 'right')
        else:
            self.padding_side = 'right'
        
        # 提取所有特殊token ID
        self.pad_id = self.vocab["[PAD]"]
        self.unk_id = self.vocab["[UNK]"]
        self.bos_id = self.vocab["<|im_start|>"]      # 对话开始
        self.eos_id = self.vocab["<|im_end|>"]        # 对话结束
        self.user_id = self.vocab["<|user|>"]  # 用户角色，向后兼容
        self.assistant_id = self.vocab["<|assistant|>"]  # 助手角色
        
        # 创建正则匹配模式（包含所有特殊token）
        # 注意：需要转义特殊字符
        self.token_pattern = re.compile(
            r"(<\|im_start\|>|<\|im_end\|>|<\|user\|>|<\|assistant\|>)"
        )
        
        # 打印tokenizer信息
        print(f"Tokenizer初始化完成:")
        print(f"  - 词汇表大小: {len(self.vocab)}")
        print(f"  - 特殊token:")
        print(f"      [PAD] = {self.pad_id}")
        print(f"      <|im_start|> = {self.bos_id}")
        print(f"      <|im_end|> = {self.eos_id}")
        print(f"      [UNK] = {self.unk_id}")
        print(f"      <|user|> = {self.user_id}")
        print(f"      <|assistant|> = {self.assistant_id}")
    
    def tokenize(self, text):
        """将文本拆分为token列表"""
        tokens = []
        for part in self.token_pattern.split(text):
            if not part or part.isspace():
                continue
            if self.token_pattern.match(part):
                tokens.append(part.strip())
            else:
                # 处理基因ID序列（可能包含多个空格分隔的ID）
                tokens.extend(part.split())
        return tokens

    def encode(self, text, max_length=None, add_special_tokens=True):
        tokens = self.tokenize(text)
        ids = [self.vocab.get(token, self.unk_id) for token in tokens]
        if max_length:
            if len(ids) > max_length:
                # 左填充时通常保留右侧（即截断左侧），但可根据需求调整
                ids = ids[-max_length:] if self.padding_side == 'left' else ids[:max_length]
            else:
                pad_len = max_length - len(ids)
                if self.padding_side == 'left':
                    ids = [self.pad_id] * pad_len + ids
                else:
                    ids = ids + [self.pad_id] * pad_len
        return ids
    
    def decode(self, ids, skip_special_tokens=False):
        """将ID序列解码回文本"""
        tokens = []
        for id_ in ids:
            if id_ == self.pad_id:  # 跳过填充标记
                continue
            token = self.id2token.get(id_, "[UNK]")
            if skip_special_tokens and token in [
                "<|im_start|>", "<|im_end|>", 
                "<|user|>", "<|assistant|>", "[UNK]"
            ]:
                continue
            tokens.append(token)
        
        # 重建原始格式（特殊token周围有空格）
        return " ".join(tokens)
    
    def get_vocab_size(self):
        """获取词汇表大小"""
        return len(self.vocab)
      
# 初始化
gene = torch.load("../gene_names.pt")
    
gene_vocab = build_gene_tokenizer(gene)  # 修改这里，传入gene而不是global_ppi
print(f"词汇表大小: {len(gene_vocab)}")

tokenizer = GeneTokenizer('../Token/vocab.json')
