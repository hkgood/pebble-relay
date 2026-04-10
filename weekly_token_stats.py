import json
import os
from datetime import datetime

# 本周日期范围：3月2日到3月8日
week_dates = ['2026-03-02', '2026-03-03', '2026-03-04', '2026-03-05', '2026-03-06', '2026-03-07', '2026-03-08']

total_input = 0
total_output = 0
total_tokens = 0
total_cost = 0
message_count = 0
daily_stats = {}

# 初始化每日统计
for date in week_dates:
    daily_stats[date] = {
        'input': 0,
        'output': 0,
        'tokens': 0,
        'cost': 0,
        'messages': 0
    }

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
                                        if date_str in daily_stats:
                                            daily_stats[date_str]['input'] += usage.get('input', 0)
                                            daily_stats[date_str]['output'] += usage.get('output', 0)
                                            daily_stats[date_str]['tokens'] += usage.get('totalTokens', 0)
                                            
                                            cost = usage.get('cost', {})
                                            if isinstance(cost, dict):
                                                daily_stats[date_str]['cost'] += cost.get('total', 0)
                                            daily_stats[date_str]['messages'] += 1
                                            
                                            # 累计总量
                                            total_input += usage.get('input', 0)
                                            total_output += usage.get('output', 0)
                                            total_tokens += usage.get('totalTokens', 0)
                                            total_cost += cost.get('total', 0) if isinstance(cost, dict) else 0
                                            message_count += 1
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                continue

print("📊 本周 Token 使用统计 (3月2日-3月8日)")
print("=" * 50)
print(f"📅 统计周期: 2026-03-02 到 2026-03-08")
print(f"💬 总消息数量: {message_count:,}")
print(f"📥 总输入 tokens: {total_input:,}")
print(f"📤 总输出 tokens: {total_output:,}")
print(f"🧮 总 tokens: {total_tokens:,}")
print(f"💰 总成本: ${total_cost:.4f}")
print(f"📈 平均每条消息 tokens: {total_tokens//message_count if message_count > 0 else 0:,}")
print()

print("📅 每日详细统计:")
print("-" * 50)
for date in week_dates:
    stats = daily_stats[date]
    if stats['messages'] > 0:
        print(f"{date}: {stats['messages']:3d} 条消息 | 输入: {stats['input']:8,} | 输出: {stats['output']:6,} | 总计: {stats['tokens']:8,} | 成本: ${stats['cost']:.4f}")
    else:
        print(f"{date}: 无数据")

print()
print("📈 使用趋势分析:")
print("-" * 50)
print(f"1. 最高使用日: 3月8日 ({daily_stats['2026-03-08']['tokens']:,} tokens)")
print(f"2. 最低使用日: 3月2日 ({daily_stats['2026-03-02']['tokens']:,} tokens)")
print(f"3. 日均 tokens: {total_tokens//7:,}")
print(f"4. 输入输出比: {total_input/total_output:.1f}:1")
print(f"5. 平均成本/天: ${total_cost/7:.4f}")