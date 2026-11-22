import json
import os
import numpy as np
from collections import defaultdict
import matplotlib.pyplot as plt
from Tokenizer import GeneTokenizer, tokenizer

def load_pretrain_data(data_path, max_samples=None):
    """加载Pretrain数据"""
    print(f"加载Pretrain数据: {data_path}")
    
    if data_path.endswith('.json'):
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查数据结构
        if isinstance(data, dict):
            if 'text' in data:
                # 单个样本
                samples = [data['text']]
            else:
                # 可能是字典列表或包含其他结构
                samples = []
                for key, value in data.items():
                    if isinstance(value, str):
                        samples.append(value)
        elif isinstance(data, list):
            samples = []
            for item in data:
                if isinstance(item, dict) and 'text' in item:
                    samples.append(item['text'])
                elif isinstance(item, str):
                    samples.append(item)
                else:
                    samples.append(str(item))
        else:
            print(f"警告: 未知的Pretrain数据结构: {type(data)}")
            return []
    else:
        print(f"错误: 不支持的文件格式: {data_path}")
        return []
    
    if max_samples and len(samples) > max_samples:
        samples = samples[:max_samples]
    
    print(f"加载了 {len(samples)} 个Pretrain样本")
    return samples

def load_sft_data(data_path, max_samples=None):
    """加载SFT数据（每行一个JSON对象）"""
    print(f"加载SFT数据: {data_path}")
    samples = []
    with open(data_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:          # 跳过空行
                continue
            item = json.loads(line)
            if 'conversations' in item:
                samples.append(item)
    if max_samples and len(samples) > max_samples:
        samples = samples[:max_samples]
    print(f"加载了 {len(samples)} 个SFT样本")
    return samples
  
def analyze_pretrain_lengths(samples, tokenizer, plot=True):
    """分析Pretrain数据长度"""
    print("\n" + "="*50)
    print("Pretrain数据长度分析")
    print("="*50)
    
    # 统计每个对话的长度
    all_lengths = []
    all_turn_lengths = []  # 每个对话中的每句话长度
    
    for sample in samples:
        # 将整个文本tokenize
        tokens = tokenizer.encode(sample)
        all_lengths.append(len(tokens))
        
        # 分割对话（如果有分隔符）
        if '<|im_end|>' in sample:
            turns = sample.split('<|im_end|>')
            for turn in turns:
                if turn.strip():  # 非空对话
                    turn_tokens = tokenizer.encode(turn.strip())
                    all_turn_lengths.append(len(turn_tokens))
    
    if not all_lengths:
        print("没有找到有效数据")
        return
    
    # 基本统计
    print(f"总样本数: {len(all_lengths)}")
    print(f"总对话轮次数: {len(all_turn_lengths)}")
    print("\n全文本长度统计:")
    print_statistics(all_lengths)
    
    if all_turn_lengths:
        print("\n单轮对话长度统计:")
        print_statistics(all_turn_lengths)
    
    # 长度分布直方图
    if plot:
        plot_length_distribution(
            all_lengths, 
            "Pretrain Sequence Length Distribution",
            "Sequence Length (token)",
            "Frequency"
        )
    
    return all_lengths

def analyze_sft_lengths(samples, tokenizer, plot=True):
    """分析SFT数据长度"""
    print("\n" + "="*50)
    print("SFT数据长度分析")
    print("="*50)
    
    # 统计长度
    all_lengths = []  # 整个对话的长度
    user_lengths = []  # 用户消息长度
    assistant_lengths = []  # 助手回复长度
    turn_counts = []  # 对话轮次数
    
    for sample in samples:
        if 'conversations' not in sample:
            continue
            
        conversations = sample['conversations']
        if not conversations:
            continue
        
        # 构建完整的对话文本（按照训练时的格式）
        full_conversation = ""
        for turn in conversations:
            role = turn.get('role', 'unknown')
            content = turn.get('content', '')
            
            # 按照可能的训练格式构建
            # 这里假设格式为: <|im_start|>{role}\n{content}<|im_end|>
            formatted_turn = f"<|im_start|>{role}\n{content}<|im_end|>"
            full_conversation += formatted_turn
            
            # 统计单条消息长度
            turn_tokens = tokenizer.encode(formatted_turn)
            if role == 'user':
                user_lengths.append(len(turn_tokens))
            elif role == 'assistant':
                assistant_lengths.append(len(turn_tokens))
        
        # 统计完整对话长度
        full_tokens = tokenizer.encode(full_conversation)
        all_lengths.append(len(full_tokens))
        turn_counts.append(len(conversations))
    
    if not all_lengths:
        print("没有找到有效数据")
        return
    
    # 基本统计
    print(f"总对话数: {len(all_lengths)}")
    print(f"总消息数: {len(user_lengths) + len(assistant_lengths)}")
    print(f"  用户消息数: {len(user_lengths)}")
    print(f"  助手消息数: {len(assistant_lengths)}")
    
    print("\n完整对话长度统计:")
    print_statistics(all_lengths)
    
    if user_lengths:
        print("\n用户消息长度统计:")
        print_statistics(user_lengths)
    
    if assistant_lengths:
        print("\n助手消息长度统计:")
        print_statistics(assistant_lengths)
    
    if turn_counts:
        print("\n对话轮次统计:")
        print_statistics(turn_counts)
    
    # 长度分布直方图
    if plot:
        plot_length_distribution(
            all_lengths,
            "SFT Sequence Length Distribution",
            "Sequence Length (token数)",
            "Frequency"
        )
    
    return all_lengths

def print_statistics(lengths):
    """打印统计信息"""
    if not lengths:
        print("  无数据")
        return
    
    lengths_array = np.array(lengths)
    
    print(f"  最小值: {lengths_array.min()}")
    print(f"  最大值: {lengths_array.max()}")
    print(f"  平均值: {lengths_array.mean():.2f}")
    print(f"  中位数: {np.median(lengths_array):.2f}")
    print(f"  标准差: {lengths_array.std():.2f}")
    
    # 百分位数
    print(f"  25%分位数: {np.percentile(lengths_array, 25):.2f}")
    print(f"  50%分位数: {np.percentile(lengths_array, 50):.2f}")
    print(f"  75%分位数: {np.percentile(lengths_array, 75):.2f}")
    print(f"  90%分位数: {np.percentile(lengths_array, 90):.2f}")
    print(f"  95%分位数: {np.percentile(lengths_array, 95):.2f}")
    print(f"  99%分位数: {np.percentile(lengths_array, 99):.2f}")
    
    # 覆盖率分析
    for threshold in [64, 128, 200, 256, 320, 384, 400, 512, 640, 768, 1024]:
        coverage = (lengths_array <= threshold).sum() / len(lengths_array) * 100
        print(f"  长度 ≤ {threshold}: {coverage:.1f}%")

def plot_length_distribution(lengths, title, xlabel, ylabel, bins=50):
  
    # 全局字体设置
    plt.rcParams['font.family'] = 'Times New Roman'
    plt.rcParams['mathtext.fontset'] = 'stix'  # 数学符号也用Times风格
    plt.rcParams['axes.unicode_minus'] = False  # 正常显示负号
    
    """绘制长度分布直方图"""
    if not lengths:
        return
    
    plt.figure(figsize=(8, 4))
    
    # 计算合适的bins
    max_len = max(lengths)
    bins = min(bins, max_len // 10)
    
    # 绘制直方图
    plt.hist(lengths, bins=bins, alpha=0.7, edgecolor='black')
    
    # 添加统计线
    mean_val = np.mean(lengths)
    median_val = np.median(lengths)
    
    plt.axvline(mean_val, color='red', linestyle='--', linewidth=2, label=f'Mean : {mean_val:.1f}')
    plt.axvline(median_val, color='green', linestyle='--', linewidth=2, label=f'Median : {median_val:.1f}')
    
    # 添加一些常见的序列长度线
    common_lengths = [64, 128, 200, 256, 320, 384, 400, 512, 640, 768, 1024]
    colors = plt.cm.tab20(np.linspace(0, 1, len(common_lengths)))
    
    for length, color in zip(common_lengths, colors):
        if length <= max_len * 1.1:  # 只在合理范围内显示
            coverage = (np.array(lengths) <= length).sum() / len(lengths) * 100
            plt.axvline(length, color=color, linestyle=':', linewidth=1, alpha=0.5)
            plt.text(length, plt.ylim()[1]*0.9, f'{length}\n({coverage:.0f}%)', 
                    ha='center', va='top', fontsize=8, rotation=90, color=color)
    
    plt.title(title, fontsize=14)
    plt.xlabel(xlabel, fontsize=12)
    plt.ylabel(ylabel, fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # 保存图片
    filename = title.replace(' ', '_').replace(':', '') + '.png'
    plt.savefig(filename, dpi=150)
    print(f"  图表已保存: {filename}")
    plt.show()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="分析Pretrain和SFT数据长度分布")
    parser.add_argument("--pretrain_path", type=str, default="../pretrain_combined.json", help="Pretrain数据路径")
    parser.add_argument("--sft_path", type=str, default="../sft_0.json", help="SFT数据路径")
    parser.add_argument("--max_samples", type=int, default=None, help="最大分析样本数（测试用）")
    parser.add_argument("--no_plot", action="store_true", help="不显示图表")
    parser.add_argument("--save_results", action="store_true", help="保存统计结果到文件")
    
    args = parser.parse_args()
    
    # 加载数据
    pretrain_samples = load_pretrain_data(args.pretrain_path, args.max_samples)
    sft_samples = load_pretrain_data(args.sft_path, args.max_samples)
    
    # 分析长度
    pretrain_results = None
    sft_results = None
    
    if pretrain_samples:
        pretrain_results = analyze_pretrain_lengths(
            pretrain_samples, 
            tokenizer, 
            plot=False
        )
        
    plot_length_distribution(
        pretrain_results, 
        "Pretrain Sequence Length Distribution",
        "Sequence Length (token)",
        "Frequency"
        )
    
    if sft_samples:
        sft_results = analyze_pretrain_lengths(
            sft_samples,
            tokenizer,
            plot=False
        )
  
    plot_length_distribution(
        sft_results,
        "SFT Sequence Length Distribution",
        "Sequence Length (token数)",
        "Frequency"
    )


if __name__ == "__main__":
    main()
