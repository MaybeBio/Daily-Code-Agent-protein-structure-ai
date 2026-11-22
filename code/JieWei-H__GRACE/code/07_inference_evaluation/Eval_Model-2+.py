import argparse
import random
import warnings
import numpy as np
import pickle
import json
from transformers import TextStreamer
from ModelLM import Config, ForCausalLM
from Tokenizer import GeneTokenizer, tokenizer
import torch
from tqdm import tqdm
import networkx as nx
import os

warnings.filterwarnings('ignore')

def load_sft_model(config, args):
    """加载SFT模型，使用给定的config"""
    model = ForCausalLM(config).to(args.device)
    moe_path = '_moe' if config.use_moe else ''
    ckp = f'../out_sft-1/full_sft_{config.hidden_size}{moe_path}_1.pth'
    state_dict = torch.load(ckp, map_location=args.device)
    model.load_state_dict(state_dict, strict=False)

    print(f'SFT模型参数量: {sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.2f}(Million)')
    return model

def load_prompt_datas():
    with open('hub_nodes_ids.pkl', 'rb') as f:
        prompt_datas = pickle.load(f)
    return prompt_datas[30]

def save_results(results, filename):
    with open(filename, 'wb') as f:
        pickle.dump(results, f)
    print(f"结果已保存到: {filename}")

def create_chat_prompt(messages, tokenizer, add_generation_prompt=True):
    formatted = []
    for turn in messages:
        role = "<|im_start|> <|user|>" if turn['role'] == 'user' else "<|assistant|>    "
        content = turn['content'].strip()
        formatted.append(f"{role} {content} ")
    result = "\n".join(formatted)
    if add_generation_prompt and messages[-1]['role'] == 'user':
        result += "<|assistant|> "
    return result

def create_sft_prompt(prompt_text, tokenizer):
    return tokenizer.decode([tokenizer.bos_id]) + prompt_text

def setup_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

def main():
    parser = argparse.ArgumentParser(description="Complex")
    parser.add_argument('--out_dir', default='out', type=str)
    parser.add_argument('--temperature', default=0.85, type=float)
    parser.add_argument('--top_p', default=0.85, type=float)
    parser.add_argument('--top_k', default=10, type=float)
    parser.add_argument('--device', default='cuda:0' if torch.cuda.is_available() else 'cpu', type=str)
    parser.add_argument('--max_seq_len', default=128, type=int)
    parser.add_argument('--hidden_size', default=512, type=int)
    parser.add_argument('--num_hidden_layers', default=16, type=int)
    parser.add_argument('--use_moe', default=False, type=bool)
    parser.add_argument('--vocab_size', type=int, default=len(tokenizer.vocab))
    parser.add_argument('--freeze_embedding', default=False, type=bool)
    parser.add_argument('--use_external_embedding', default=False, type=bool)
    parser.add_argument('--use_annotation_bias', default=True, type=bool)
    parser.add_argument('--history_cnt', default=0, type=int)
    parser.add_argument('--output_file', default='generation_results-4.pkl', type=str)
    parser.add_argument('--seed', default=20030201, type=int)
    parser.add_argument('--rounds', default=1, type=int)

    # ========== 新增：推理偏置相关参数（预训练和SFT独立控制） ==========
    parser.add_argument('--use_bias', type=bool, default=True, help='模型生成时是否使用偏置')
    parser.add_argument('--bias_path', type=str, default="../integrated_similarity_All.pt", help='偏置矩阵文件路径')
    parser.add_argument('--bias_alpha', type=float, default=2.0, help='偏置强度系数')
    # =================================================================
    
    args = parser.parse_args()

    # 为预训练模型创建配置
    config = Config(
        hidden_size=args.hidden_size,
        num_hidden_layers=args.num_hidden_layers,
        use_moe=args.use_moe,
        freeze_embedding=args.freeze_embedding,
        use_external_embedding=args.use_external_embedding,
        use_annotation_bias=args.use_annotation_bias,
        vocab_size=args.vocab_size,
        use_inference_bias=args.use_bias,
        inference_bias_path=args.bias_path,
        bias_alpha=args.bias_alpha
    )

    # 加载两个模型，分别传入各自的配置
    model_sft = load_sft_model(config, args)
    model_sft.eval()

    # 获取PPI图（如果需要）
    with open('../Graph_init/graph.pkl', 'rb') as f:
        graph = pickle.load(f)

    prompts = load_prompt_datas()
    print(f"加载了 {len(prompts)} 个提示")
    
    all_results = []
    
    for idx, prompt in enumerate(tqdm(prompts, desc=f"Hub Proteins")):
        setup_seed(args.seed + idx)
        
        # ========== 第一阶段：使用预训练模型生成基因序列 ==========
        sft_prompt = create_sft_prompt(prompt, tokenizer)
        sft_input_ids = tokenizer.encode(sft_prompt, max_length=args.max_seq_len)
        sft_inputs = {
            "input_ids": torch.tensor([sft_input_ids]).to(args.device),
            "attention_mask": torch.tensor([[1] * len(sft_input_ids)]).to(args.device)
        }

        with torch.no_grad():
            sft_generated_ids = model_sft.generate(
                sft_inputs["input_ids"],
                max_new_tokens=args.max_seq_len,
                do_sample=True,
                attention_mask=sft_inputs["attention_mask"],
                pad_token_id=tokenizer.pad_id,
                eos_token_id=tokenizer.eos_id,
                top_p=args.top_p,
                temperature=args.temperature,
                top_k=args.top_k
            )
        
        sft_input_length = sft_inputs["input_ids"].shape[1]
        generated_gene_ids = sft_generated_ids[0][sft_input_length:].cpu().tolist()
        generated_gene_sequence = tokenizer.decode(generated_gene_ids, skip_special_tokens=True)
        full_sequence = prompt + " " + generated_gene_sequence 
        full_sequence

        result = {
            "prompt_id": idx,
            "original_prompt": prompt,
            "sft_response": full_sequence,
        }
        all_results.append(result)

    save_results(all_results, args.output_file)
    print(f"处理完成！共处理 {len(all_results)} 个提示")

if __name__ == "__main__":
    main()
