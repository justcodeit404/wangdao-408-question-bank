#!/usr/bin/env python3
"""修复计算机网络 X23 page 29 多填空选择题：拆成 5 道独立子题。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # oneoff/ -> scripts/ -> bank-408/
PATH = ROOT / 'output' / 'questions_net.json'

# 原题答案（来自 page_032.json）：B D C A B
SUBS = [
    {
        'id': 'X23_1',
        'content': '在 OSI 参考模型中，提供流量控制功能的层是第（ ）层。',
        'options': {'A': '1、2、3', 'B': '2、3、4', 'C': '3、4、5', 'D': '4、5、6'},
        'answer': {'choice': 'B', 'explanation': ''},
    },
    {
        'id': 'X23_2',
        'content': '在 OSI 参考模型中，提供建立、维护和拆除端到端的连接的层是（ ）。',
        'options': {'A': '物理层', 'B': '数据链路层', 'C': '会话层', 'D': '传输层'},
        'answer': {'choice': 'D', 'explanation': ''},
    },
    {
        'id': 'X23_3',
        'content': '在 OSI 参考模型中，为数据分组提供在网络中路由功能的是（ ）。',
        'options': {'A': '物理层', 'B': '数据链路层', 'C': '网络层', 'D': '传输层'},
        'answer': {'choice': 'C', 'explanation': ''},
    },
    {
        'id': 'X23_4',
        'content': '在 OSI 参考模型中，传输层提供（ ）的数据传送。',
        'options': {'A': '主机进程之间', 'B': '网络之间', 'C': '数据链路之间', 'D': '物理线路之间'},
        'answer': {'choice': 'A', 'explanation': ''},
    },
    {
        'id': 'X23_5',
        'content': '在 OSI 参考模型中，为网络层实体提供数据发送和接收功能及过程的是（ ）。',
        'options': {'A': '物理层', 'B': '数据链路层', 'C': '会话层', 'D': '传输层'},
        'answer': {'choice': 'B', 'explanation': ''},
    },
]


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    for ch in data.get('chapters', []):
        questions = ch.get('questions', [])
        for i, q in enumerate(questions):
            if q.get('id') == 'X23' and q.get('page') == 29:
                # 保留公共字段
                base = {
                    'type': '选择题',
                    'page': 29,
                    'bbox': q.get('bbox'),
                    'has_image': False,
                    'image_ref': None,
                    'topic_title': q.get('topic_title'),
                    'q_pages': q.get('q_pages'),
                    'a_pages': q.get('a_pages'),
                    'sub_questions': None,
                }
                new_qs = []
                for sub in SUBS:
                    new_qs.append({**base, **sub})
                questions[i:i+1] = new_qs
                ch['question_count'] = len(questions)
                print(f'replaced X23 page 29 with {len(new_qs)} sub-questions')
                break
    data['total_questions'] = sum(ch['question_count'] for ch in data.get('chapters', []))
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'total questions: {data["total_questions"]}')


if __name__ == '__main__':
    main()
