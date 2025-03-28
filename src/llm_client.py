from openai import OpenAI
import sys

import os
import configparser

#获取当前文件的绝对路径，向上一级，用绝对路径找到config.ini并读取
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
config_path = os.path.join(project_root, 'config.ini')
MYCONFIG = configparser.ConfigParser()
MYCONFIG.read(config_path,encoding='utf-8')

def update_response(new_text):
    #作为回调函数，更新response
    print(new_text, end="", flush=True,sep="")

class LLMClient:
    def __init__(self, api_url=MYCONFIG['DEFAULT']['API_URL'],api_key=MYCONFIG['DEFAULT']['API_KEY'],model=MYCONFIG['DEFAULT']['MODEL']):
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_url
        )
        self.model = model

    def get_response(self, prompt, callback=None):
        model = self.model
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        full_response = ""
        for chunk in response:
            if not chunk.choices:
                continue
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                if callback:
                    callback(content)
            if chunk.choices[0].delta.reasoning_content:
                reasoning = chunk.choices[0].delta.reasoning_content
                full_response += reasoning
                if callback:
                    callback(reasoning)
        return full_response



if __name__ == "__main__":
    # 需要先设置环境变量 SILICONFLOW_API_KEY
    import os
    client = LLMClient()
    
    print(client.get_response("请你作为一个熟悉人工智能知识的专业算法工程师帮助我。我正在参加一场面试，接下来你被输入的文字来自于面试官的语音转文字，请你全力理解并为我写好合适的回答：听你刚刚的介绍，你在训练模型的过程中遇到过拟合了怎么办？", callback=update_response))