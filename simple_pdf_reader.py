#!/usr/bin/env python3
import re
import os

def extract_text_from_pdf_binary(pdf_path):
    """尝试从PDF二进制文件中提取文本内容"""
    try:
        with open(pdf_path, 'rb') as f:
            data = f.read()
        
        # 尝试解码为UTF-8，但PDF可能包含二进制数据
        # 我们尝试提取所有可打印的ASCII字符
        text = ""
        for i in range(0, len(data), 1024):
            chunk = data[i:i+1024]
            try:
                # 尝试解码为UTF-8
                decoded = chunk.decode('utf-8', errors='ignore')
                # 只保留可打印字符
                printable = ''.join(c for c in decoded if c.isprintable() or c in '\n\r\t')
                text += printable
            except:
                # 如果解码失败，尝试提取ASCII字符
                ascii_chars = ''.join(chr(b) for b in chunk if 32 <= b < 127)
                text += ascii_chars
        
        return text
    except Exception as e:
        return f"读取错误: {e}"

def analyze_pdf_content(text):
    """分析提取的文本内容"""
    if not text or len(text) < 100:
        return "文本内容太少或无法提取"
    
    # 查找可能的结构
    lines = text.split('\n')
    
    # 查找标题和表头
    print("查找可能的标题和表头:")
    for i, line in enumerate(lines[:50]):
        if len(line.strip()) > 10:
            print(f"{i+1}: {line[:100]}")
    
    # 查找数字和编号（可能是项目编号）
    print("\n查找数字模式（可能是项目编号）:")
    number_pattern = re.compile(r'\b\d+\b')
    for i, line in enumerate(lines[:100]):
        if number_pattern.search(line):
            print(f"{i+1}: {line[:100]}")
    
    # 查找学校、年级等关键词
    keywords = ['小学', '中学', '年级', '学校', '项目', '作品', '名称', '作者']
    print("\n查找关键词:")
    for i, line in enumerate(lines[:200]):
        if any(keyword in line for keyword in keywords):
            print(f"{i+1}: {line[:100]}")
    
    return "分析完成"

if __name__ == "__main__":
    pdf_files = [
        "发明作品入围名单.pdf",
        "人工智能作品入围名单.pdf", 
        "创意作品入围名单.pdf",
        "科技绘画作品展示名单.pdf"
    ]
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join("/Users/liuyilin/.openclaw/workspace", pdf_file)
        if os.path.exists(pdf_path):
            print(f"\n{'='*60}")
            print(f"分析文件: {pdf_file}")
            print(f"{'='*60}")
            
            # 提取文本
            text = extract_text_from_pdf_binary(pdf_path)
            print(f"提取的文本长度: {len(text)} 字符")
            
            if len(text) > 1000:
                print("\n前1000字符:")
                print(text[:1000])
                print("\n...")
                print("最后500字符:")
                print(text[-500:])
                
                # 分析内容
                analyze_pdf_content(text)
            else:
                print("文本内容:")
                print(text)
        else:
            print(f"文件不存在: {pdf_path}")