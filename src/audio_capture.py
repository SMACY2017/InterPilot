# audio_capture.py
import sys
if sys.platform == "win32":
    import pyaudiowpatch as pyaudio
else:
    import pyaudio
import wave
import os
import configparser
#获取当前文件的绝对路径，向上一级，用绝对路径找到config.ini并读取
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
config_path = os.path.join(project_root, 'config.ini')
MYCONFIG = configparser.ConfigParser()
MYCONFIG.read(config_path,encoding='utf-8')

class LoopbackRecorder:
    def __init__(self, device_index=MYCONFIG['DEFAULT'].getint('SPEAKER_DEVICE_INDEX')):
        # 初始化
        self.p = None
        self.stream = None
        self.wave_file = None
        
        self.is_recording = False
        self.device_index = None if device_index < 0 else device_index
        self.device_info = self._get_device()
        
    def _cleanup(self):
        """严格遵循示例的资源释放顺序"""
        print("正在清理资源...")
        if self.is_recording:
            self.is_recording = False
        if self.stream:
            self.stream.close()
        if self.wave_file:
            self.wave_file.close()
        if self.p:
            self.p.terminate()

    def _get_device(self):
        """严格遵循官方示例的设备获取方式"""
        self.p = pyaudio.PyAudio()
        try:
            if self.device_index is None:
                if sys.platform == "win32":
                    self.device_info = self.p.get_default_wasapi_loopback()  
                else:
                    self.device_info = self.p.get_default_input_device_info()
            else:
                self.device_info = self.p.get_device_info_by_index(self.device_index)
                
            # 验证设备是否支持loopback
            if self.device_info["maxInputChannels"] < 1:
                raise ValueError("设备不支持loopback输入")
                
            return self.device_info
        except (OSError, LookupError) as e:
            raise RuntimeError(f"设备初始化失败: {str(e)}")

    def start_recording(self, filename="output.wav"):
        """完全按照官方示例的流初始化方式"""
        try:
            self._get_device()
            
            # 参数直接从设备信息获取
            self.rate = int(self.device_info["defaultSampleRate"])
            self.channels = self.device_info["maxInputChannels"]
            self.format = pyaudio.paInt16
            self.sample_size = self.p.get_sample_size(self.format)

            # 初始化WAV文件
            self.wave_file = wave.open(filename, 'wb')
            self.wave_file.setnchannels(self.channels)
            self.wave_file.setsampwidth(self.sample_size)
            self.wave_file.setframerate(self.rate)

            # 创建音频流（与示例完全一致）
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=self.device_info["index"],
                frames_per_buffer=1024
            )

            self.is_recording = True
            print(f"成功启动录音: {self.device_info['name']}")

        except Exception as e:
            self._cleanup()
            raise RuntimeError("self._cleanup()出错")

    def record(self, duration=None):
        if not self.is_recording:
            raise RuntimeError("必须先调用start_recording()")
        try:
            if duration:  # 定时录音模式
                print(f"正在录制 {duration} 秒...")
                for _ in range(0, int(self.rate / 1024 * duration)):
                    if not self.is_recording:  # 检查是否收到停止信号
                        break
                    data = self.stream.read(1024)
                    self.wave_file.writeframes(data)
            else:  # 持续录音模式
                print("持续录音中...")
                while self.is_recording:
                    data = self.stream.read(1024)
                    self.wave_file.writeframes(data)
                self.stop_recording()
        finally:
            self._cleanup()
            print("录音已停止")

    def stop_recording(self):
        """严格遵循示例的资源释放顺序"""
        if self.is_recording:
            self.is_recording = False
        if self.stream:
            self.stream.close()
        if self.wave_file:
            self.wave_file.close()
        if self.p:
            self.p.terminate()
        print("录音已安全停止")

    @staticmethod
    def list_devices():
        """设备列表查询（直接使用官方推荐方式）"""
        p = pyaudio.PyAudio()
        # with pyaudio.PyAudio() as p:
            # 打印默认输入设备信息
        print("\n=== 默认输入设备 ===")
        try:
            default = p.get_default_input_device_info()
            print(f"* 默认设备: [{default['index']}] {default['name']}")
        except Exception as e:
            print("! 未找到默认输入设备")

        # 打印默认输出设备信息
        print("\n=== 默认输出设备 ===")
        try:
            default = p.get_default_output_device_info()
            print(f"* 默认设备: [{default['index']}] {default['name']}")
        except Exception as e:
            print("! 未找到默认输出设备")

        print("\n=== 默认Loopback设备 ===")
        try:
            if sys.platform == "win32":
                device = p.get_default_wasapi_loopback()  
            else:
                device = p.get_default_input_device_info()
            print(f"* 默认设备: [{default['index']}] {default['name']}")
        except Exception as e:
            print("! 未找到默认loopback设备")

        print("\n所有含有InputChannel的设备:")
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev["maxInputChannels"] > 0:
                print(f"[{dev['index']}] {dev['name']} (输入通道: {dev['maxInputChannels']})")

        print("\n所有含有OutputChannel的设备:")
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev["maxOutputChannels"] > 0:
                print(f"[{dev['index']}] {dev['name']} (输出通道: {dev['maxOutputChannels']})")
        
        print("\n所有含有Loopback的设备:")
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice") != None and dev["isLoopbackDevice"] > 0:
                print(f"[{dev['index']}] {dev['name']} (Loopback: {dev['maxInputChannels']})")
        
        p.terminate()

if __name__ == "__main__":
    # 列出设备
    LoopbackRecorder.list_devices()
    
    try:
        recorder = LoopbackRecorder()  # 明确指定设备索引
        recorder.start_recording("output/test_record.wav")
        recorder.record(duration=5)  # 录制5秒
        recorder.stop_recording()
    except Exception as e:
        print(f"录音失败: {str(e)}")
