import json
import os
from datetime import datetime

# 本周日期范围：3月2日到3月8日
week_dates = ['2026-03-02', '2026-03-03', '2026-03-04', '2026-03-05', '2026-03-06', '2026-03-07', '2026-03-08']

model_stats = {}
total_tokens = 0

# 遍历所有会话文件
sessions_dir = '/Users/liuyilin/.openclaw/agents/main/sessions'
if os.path.exists(sessions_dir):
    for filename in os.listdir(sessions_dir):
        if filename.endswith('.jsonl'):
            filepath = os.path.join(sessions_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            if data.get('type') == 'message' and 'message' in data:
                                msg = data['message']
                                if 'usage' in msg:
                                    usage = msg['usage']
                                    timestamp = data.get('timestamp', '')
                                    
                                    # 提取日期
                                    if timestamp:
                                        date_str = timestamp[:10]  # 获取 YYYY-MM-DD
                                        
                                        # 检查是否在本周内
                                        if date_str in week_dates:
                                            provider = msg.get('provider', 'unknown')
                                            model = msg.get('model', 'unknown')
                                            model_key = f"{provider}/{model}"
                                            
                                            if model_key not in model_stats:
                                                model_stats[model_key] = {
                                                    'input': 0,
                                                    'output': 0,
                                                    'tokens': 0,
                                                    'messages': 0
                                                }
                                            
                                            model_stats[model_key]['input'] += usage.get('input', 0)
                                            model_stats[model_key]['output'] += usage.get('output', 0)
                                            model_stats[model_key]['tokens'] += usage.get('totalTokens', 0)
                                            model_stats[model_key]['messages'] += 1
                                            total_tokens += usage.get('totalTokens', 0)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                continue

print("🤖 本周各模型 Token 使用统计 (3月2日-3月8日)")
print("=" * 60)
print(f"📅 统计周期: 2026-03-02 到 2026-03-08")
print(f"🧮 总 tokens: {total_tokens:,}")
print()

print("📊 模型使用排名:")
print("-" * 60)
print(f"{'模型':<40} {'消息数':<8} {'输入 tokens':<12} {'输出 tokens':<12} {'总 tokens':<12} {'占比':<6}")
print("-" * 60)

# 按总 tokens 排序
sorted_models = sorted(model_stats.items(), key=lambda x: x[1]['tokens'], reverse=True)

for model_key, stats in sorted_models:
    percentage = (stats['tokens'] / total_tokens * 100) if total_tokens > 0 else 0
    print(f"{model_key:<40} {stats['messages']:<8,} {stats['input']:<12,} {stats['output']:<12,} {stats['tokens']:<12,} {percentage:>5.1f}%")

print()
print("📈 使用分析:")
print("-" * 60)
if sorted_models:
    top_model = sorted_models[0]
    print(f"1. 最常用模型: {top_model[0]} ({top_model[1]['tokens']:,} tokens, {(top_model[1]['tokens']/total_tokens*100):.1f}%)")
    
    # 计算平均输入输出比
    total_input = sum(stats['input'] for _, stats in sorted_models)
    total_output = sum(stats['output'] for _, stats in sorted_models)
    if total_output > 0:
        print(f"2. 总体输入输出比: {total_input/total_output:.1f}:1")
    
    print(f"3. 使用模型数量: {len(sorted_models)}")
    print(f"4. 平均每条消息 tokens: {total_tokens//sum(stats['messages'] for _, stats in sorted_models):,}")