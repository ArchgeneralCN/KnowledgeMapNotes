#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys

def extract_messages(data):
    """
    提取消息：type=0（非[系统消息]）或 type=24
    返回 [(accountName, content), ...]
    """
    messages = data.get('messages', [])
    results = []
    for msg in messages:
        msg_type = msg.get('type')
        content = msg.get('content', '')
        account = msg.get('accountName', '')
        if msg_type == 0 and content != '[系统消息]':
            results.append((account, content))
        elif msg_type == 24:
            results.append((account, content))
    return results

def main():
    # 输入文件：第一个参数 或 标准输入
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    extracted = extract_messages(data)

    # 输出文件：第二个参数 或 默认 result.txt
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'result.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        for account, content in extracted:
            f.write(f"{account}:{content}\n")

    print(f"结果已写入 {output_file}")

if __name__ == '__main__':
    main()