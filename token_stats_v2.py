import json
import os
from datetime import datetime, timedelta

# 设置本周的日期范围（3月2日到3月8日）
start_date = datetime(2026, 3, 2)
end_date = datetime(2026, 3, 8, 23, 59, 59)

print(f'统计周期: {start_date.strftime("%Y-%m-%d")} 到 {end_date.strftime("%Y-%m-%d")}')

total_input = 0
total_output = 0
total_cache_read = 0
total_cache_write = 0
total_tokens = 0
total_cost = 0
session_count = 0

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
                                    
                                    # 检查时间是否在本周内
                                    if timestamp:
                                        try:
                                            # 处理时间戳格式
                                            if timestamp.endswith('Z'):
                                                timestamp = timestamp[:-1] + '+00:00'
                                            msg_time = datetime.fromisoformat(timestamp)
                                            
                                            if start_date <= msg_time <= end_date:
                                                total_input += usage.get('input', 0)
                                                total_output += usage.get('output', 0)
                                                total_cache_read += usage.get('cacheRead', 0)
                                                total_cache_write += usage.get('cacheWrite', 0)
                                                total_tokens += usage.get('totalTokens', 0)
                                                
                                                cost = usage.get('cost', {})
                                                if isinstance(cost, dict):
                                                    total_cost += cost.get('total', 0)
                                                session_count += 1
                                        except Exception as e:
                                            # print(f"时间解析错误: {e}")
                                            continue
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                # print(f"文件读取错误 {filepath}: {e}")
                continue

print(f'会话数量: {session_count}')
print(f'输入 tokens: {total_input:,}')
print(f'输出 tokens: {total_output:,}')
print(f'缓存读取 tokens: {total_cache_read:,}')
print(f'缓存写入 tokens: {total_cache_write:,}')
print(f'总 tokens: {total_tokens:,}')
print(f'总成本: ${total_cost:.4f}')
if session_count > 0:
    print(f'平均每次会话 tokens: {total_tokens//session_count:,}')
else:
    print('平均每次会话 tokens: 0')