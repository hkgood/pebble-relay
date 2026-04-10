#!/usr/bin/env python3
import sys
import os

# 尝试多种PDF读取方法
def try_read_pdf(pdf_path):
    print(f"尝试读取PDF: {pdf_path}")
    print(f"文件大小: {os.path.getsize(pdf_path)} bytes")
    
    # 方法1: 使用pdfminer.six
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(pdf_path)
        print("使用pdfminer.six成功提取文本")
        print(f"文本长度: {len(text)} 字符")
        print("前1000字符:")
        print(text[:1000])
        return text
    except ImportError:
        print("pdfminer.six未安装")
    except Exception as e:
        print(f"pdfminer.six错误: {e}")
    
    # 方法2: 使用PyPDF2
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()
            print("使用PyPDF2成功提取文本")
            print(f"文本长度: {len(text)} 字符")
            print("前1000字符:")
            print(text[:1000])
            return text
    except ImportError:
        print("PyPDF2未安装")
    except Exception as e:
        print(f"PyPDF2错误: {e}")
    
    # 方法3: 使用命令行工具
    try:
        import subprocess
        # 尝试使用pdftotext
        result = subprocess.run(['pdftotext', pdf_path, '-'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            text = result.stdout
            print("使用pdftotext成功提取文本")
            print(f"文本长度: {len(text)} 字符")
            print("前1000字符:")
            print(text[:1000])
            return text
        else:
            print("pdftotext未安装或失败")
    except Exception as e:
        print(f"命令行工具错误: {e}")
    
    print("所有PDF读取方法都失败了")
    return None

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
            print("\n" + "="*60)
            text = try_read_pdf(pdf_path)
            if text:
                # 简单分析文本内容
                lines = text.split('\n')
                print(f"\n行数: {len(lines)}")
                print("前20行:")
                for i, line in enumerate(lines[:20]):
                    if line.strip():
                        print(f"{i+1}: {line[:100]}")
        else:
            print(f"文件不存在: {pdf_path}")