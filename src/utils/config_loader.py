# src/utils/config_loader.py
import os
import configparser

def get_config():
    # 获取当前文件的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 向上回溯两级到项目根目录（workspace/）
    project_root = os.path.dirname(os.path.dirname(current_dir))
    config_path = os.path.join(project_root, 'config.ini')
    
    config = configparser.ConfigParser()
    config.read(config_path)


    return config