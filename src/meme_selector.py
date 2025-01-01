import json
import keyboard
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from io import BytesIO
import win32gui
import win32con
import win32clipboard
import time
from pathlib import Path
from .utils.debouncer import Debouncer
from threading import Thread, Lock
from queue import Queue
import opencc

class MemeSelector:
    def __init__(self):
        try:
            print("\n=== 初始化 MemeSelector ===")
            
            # 检查程序目录结构
            required_dirs = {
                '配置目录': Path(__file__).parent.parent / 'config',
                '图片目录': Path(__file__).parent.parent / 'images',
                '数据目录': Path(__file__).parent.parent / 'data'
            }
            
            # 保存图片目录路径
            self.images_path = required_dirs['图片目录']
            
            for name, path in required_dirs.items():
                if not path.exists():
                    print(f"创建{name}: {path}")
                    path.mkdir(parents=True, exist_ok=True)
                print(f"✓ {name}: {path}")

            # 检查必要文件
            config_path = required_dirs['配置目录'] / 'config.json'
            if not config_path.exists():
                # 创建默认配置
                default_config = {
                    "ui": {
                        "preview_size": {"width": 200},
                        "window_style": {
                            "opacity": 0.95,
                            "bg_color": "#ffffff",
                            "title_bg": "#f0f0f0",
                            "text_color": "#333333",
                            "button_bg": "#e0e0e0",
                            "button_hover": "#d0d0d0",
                            "accent_color": "#4a90e2"
                        },
                        "layout": {"padding": 10}
                    },
                    "features": {
                        "search": {"score_threshold": 30}
                    }
                }
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                print(f"已创建默认配置文件: {config_path}")

            # 加载配置
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                print("✓ 配置加载成功")
            except Exception as e:
                print(f"配置文件加载失败: {e}")
                raise

            # 检查图片映射文件
            map_path = required_dirs['数据目录'] / 'image_map.json'
            if not map_path.exists():
                # 创建空的图片映射文件
                with open(map_path, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                print(f"已创建空的图片映射文件: {map_path}")
                messagebox.showwarning("初始化提示", 
                    "检测到首次运行，请将表情包图片放入images目录，并运行索引工具生成图片映射。")

            # 检查 OpenCC 依赖
            try:
                import opencc
                self.s2t = opencc.OpenCC('s2t')
                self.t2s = opencc.OpenCC('t2s')
                print("✓ 初始化繁简转换器")
            except ImportError:
                print("错误: 缺少 OpenCC 依赖")
                messagebox.showerror("错误", 
                    "缺少必要的 OpenCC 组件，请确保正确安装了 OpenCC-Python。\n"
                    "可以通过运行 'pip install opencc-python-reimplemented' 安装。")
                raise

            # 加载图片映射
            self.image_map = self.load_image_map()
            print(f"✓ 加载了 {len(self.image_map)} 个图片映射")
            
            # 初始化变量
            self.pinyin_buffer = ""
            self.current_window = None
            self.is_running = True
            self.popup_queue = Queue()  # 添加队列用于窗口创建请求
            self.photo_references = {}  # 改用字典存储图片引用
            
            # 初始化主窗口（在主线程中）
            self.root = None  # 先不创建主窗口
            
            print("=== 初始化完成 ===\n")
            
        except Exception as e:
            print(f"初始化失败: {e}")
            messagebox.showerror("初始化失败", 
                f"程序初始化失败，请检查以下内容：\n"
                f"1. 程序目录下是否有 config、images、data 文件夹\n"
                f"2. 是否已安装 OpenCC 组件\n"
                f"3. 图片目录中是否有表情包图片\n"
                f"4. 是否已运行索引工具生成图片映射\n\n"
                f"错误信息: {str(e)}")
            raise

    def check_popup_queue(self):
        """检查是否需要创建弹窗"""
        try:
            while not self.popup_queue.empty():
                memes = self.popup_queue.get_nowait()
                self._create_popup(memes)
        except Exception as e:
            print(f"检查弹窗队列错误: {e}")
        finally:
            self.root.after(100, self.check_popup_queue)

    def create_popup(self, memes):
        """将弹窗请求添加到队列"""
        self.popup_queue.put(memes)

    def _create_popup(self, memes):
        """实际创建弹窗的方法"""
        try:
            # 清理旧窗口
            if self.current_window and self.current_window.winfo_exists():
                self.current_window.destroy()
            
            # 清理旧图片引用
            self.photo_references.clear()
            
            # 预加载所有图片
            for meme in memes['urls']:
                try:
                    img = Image.open(meme['url'])
                    aspect_ratio = img.width / img.height
                    preview_width = self.config['ui']['preview_size']['width']
                    preview_height = int(preview_width / aspect_ratio)
                    
                    img = img.resize(
                        (preview_width, preview_height),
                        Image.Resampling.LANCZOS
                    )
                    photo = ImageTk.PhotoImage(img)
                    self.photo_references[meme['url']] = photo
                except Exception as e:
                    print(f"预加载图片失败 {meme['url']}: {e}")
            
            # 创建新窗口
            window = tk.Toplevel(self.root)
            self.current_window = window
            window.overrideredirect(True)
            window.attributes('-topmost', True)
            window.attributes('-alpha', self.config['ui']['window_style']['opacity'])
            
            # 创建主框架
            main_frame = tk.Frame(
                window,
                bg=self.config['ui']['window_style']['bg_color']
            )
            main_frame.pack(expand=True, fill=tk.BOTH)
            
            # 创建标题栏
            title_frame = tk.Frame(
                main_frame,
                bg=self.config['ui']['window_style']['title_bg'],
                height=40
            )
            title_frame.pack(fill=tk.X)
            title_frame.pack_propagate(False)
            
            # 添加标题文本
            title_label = tk.Label(
                title_frame,
                text="表情包选择器",
                bg=self.config['ui']['window_style']['title_bg'],
                fg=self.config['ui']['window_style']['text_color'],
                font=('Microsoft YaHei UI', 11)
            )
            title_label.pack(side=tk.LEFT, padx=15)
            
            # 添加关闭按钮
            close_btn = tk.Label(
                title_frame,
                text='×',
                bg=self.config['ui']['window_style']['title_bg'],
                fg=self.config['ui']['window_style']['text_color'],
                font=('Arial', 18),
                cursor='hand2'
            )
            close_btn.pack(side=tk.RIGHT, padx=15)
            
            # 创建内容区域
            content_frame = tk.Frame(
                main_frame,
                bg=self.config['ui']['window_style']['bg_color'],
                padx=self.config['ui']['layout']['padding'],
                pady=self.config['ui']['layout']['padding']
            )
            content_frame.pack(expand=True, fill=tk.BOTH)
            
            # 当前图片索引
            current_index = tk.IntVar(value=0)
            total_images = len(memes['urls'])
            
            def change_image(delta):
                """切换图片"""
                new_index = current_index.get() + delta
                if 0 <= new_index < total_images:
                    current_index.set(new_index)
                    update_image(new_index)
            
            # 创建导航按钮框架
            nav_frame = tk.Frame(
                content_frame,
                bg=self.config['ui']['window_style']['bg_color']
            )
            nav_frame.pack(fill=tk.X, pady=(0, 10))
            
            # 创建按钮样式
            button_style = {
                'bg': self.config['ui']['window_style']['button_bg'],
                'fg': self.config['ui']['window_style']['text_color'],
                'font': ('Microsoft YaHei UI', 14),
                'width': 3,
                'cursor': 'hand2',
                'relief': 'flat'
            }
            
            # 上一张按钮
            prev_btn = tk.Label(
                nav_frame,
                text="◀",
                **button_style
            )
            prev_btn.pack(side=tk.LEFT)
            
            # 绑定按钮事件和悬停效果
            prev_btn.bind('<Button-1>', lambda e: change_image(-1))
            prev_btn.bind('<Enter>', lambda e: prev_btn.configure(bg=self.config['ui']['window_style']['button_hover']))
            prev_btn.bind('<Leave>', lambda e: prev_btn.configure(bg=self.config['ui']['window_style']['button_bg']))
            
            # 下一张按钮
            next_btn = tk.Label(
                nav_frame,
                text="▶",
                **button_style
            )
            next_btn.pack(side=tk.RIGHT)
            
            # 绑定按钮事件和悬停效果
            next_btn.bind('<Button-1>', lambda e: change_image(1))
            next_btn.bind('<Enter>', lambda e: next_btn.configure(bg=self.config['ui']['window_style']['button_hover']))
            next_btn.bind('<Leave>', lambda e: next_btn.configure(bg=self.config['ui']['window_style']['button_bg']))
            
            # 创建图片容器
            image_frame = tk.Frame(
                content_frame,
                bg=self.config['ui']['window_style']['bg_color']
            )
            image_frame.pack(expand=True, fill=tk.BOTH)
            
            # 创建图片标签
            image_label = tk.Label(
                image_frame,
                bg=self.config['ui']['window_style']['bg_color'],
                cursor='hand2'
            )
            image_label.pack(expand=True)
            
            # 创建信息框架
            info_frame = tk.Frame(
                content_frame,
                bg=self.config['ui']['window_style']['bg_color']
            )
            info_frame.pack(fill=tk.X, pady=(10, 0))
            
            # 创建名称标签
            name_label = tk.Label(
                info_frame,
                bg=self.config['ui']['window_style']['bg_color'],
                fg=self.config['ui']['window_style']['text_color'],
                font=('Microsoft YaHei UI', 10)
            )
            name_label.pack()
            
            # 创建分数标签
            score_label = tk.Label(
                info_frame,
                bg=self.config['ui']['window_style']['bg_color'],
                fg=self.config['ui']['window_style']['accent_color'],
                font=('Microsoft YaHei UI', 9)
            )
            score_label.pack()
            
            def update_image(index):
                """更新显示的图片"""
                try:
                    meme = memes['urls'][index]
                    url = meme['url']
                    
                    if url in self.photo_references:
                        # 使用预加载的图片
                        photo = self.photo_references[url]
                        image_label.configure(image=photo)
                        image_label.image = photo
                        
                        # 更新其他信息
                        name_label.configure(text=f"{meme['alt']} ({index + 1}/{total_images})")
                        prev_btn.configure(state=tk.NORMAL if index > 0 else tk.DISABLED)
                        next_btn.configure(state=tk.NORMAL if index < total_images - 1 else tk.DISABLED)
                        
                        score_text = f"匹配度: {meme.get('score', 0)}分"
                        if 'debug_info' in meme:
                            score_text += f" (匹配率: {meme['debug_info']['name_match']:.0%})"
                        score_label.configure(text=score_text)
                    else:
                        print(f"错误：图片未预加载 {url}")
                        
                except Exception as e:
                    print(f"更新图片显示失败: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 绑定点击事件
            image_label.bind('<Button-1>', lambda e: self.send_meme(memes['urls'][current_index.get()]['url'], window))
            
            # 绑定键盘快捷键
            window.bind('<Left>', lambda e: change_image(-1))
            window.bind('<Right>', lambda e: change_image(1))
            window.bind('<Return>', lambda e: self.send_meme(memes['urls'][current_index.get()]['url'], window))
            window.bind('<Escape>', lambda e: window.destroy())
            
            # 窗口关闭时清理引用
            def on_window_close():
                self.photo_references.clear()
                window.destroy()
            
            window.protocol("WM_DELETE_WINDOW", on_window_close)
            close_btn.bind('<Button-1>', lambda e: on_window_close())
            
            # 绑定关闭按钮事件和悬停效果
            close_btn.bind('<Button-1>', lambda e: on_window_close())
            close_btn.bind('<Enter>', lambda e: close_btn.configure(fg='#ff4444'))
            close_btn.bind('<Leave>', lambda e: close_btn.configure(fg=self.config['ui']['window_style']['text_color']))
            
            # 立即显示第一张图片
            update_image(0)
            
            # 窗口拖动功能
            def start_move(event):
                window.x = event.x
                window.y = event.y
            
            def on_motion(event):
                deltax = event.x - window.x
                deltay = event.y - window.y
                x = window.winfo_x() + deltax
                y = window.winfo_y() + deltay
                window.geometry(f"+{x}+{y}")
            
            title_frame.bind('<Button-1>', start_move)
            title_frame.bind('<B1-Motion>', on_motion)
            title_label.bind('<Button-1>', start_move)
            title_label.bind('<B1-Motion>', on_motion)
            
            # 调整窗口位置
            window.update()
            cursor_x, cursor_y = win32gui.GetCursorPos()
            window_width = window.winfo_width()
            window_height = window.winfo_height()
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            
            # 计算窗口位置（优先放在鼠标右上方）
            x = cursor_x + 10  # 鼠标右侧10像素
            y = cursor_y - window_height - 10  # 鼠标上方10像素
            
            # 如果右边放不下，就放左边
            if x + window_width > screen_width:
                x = cursor_x - window_width - 10
            
            # 如果上面放不下，就放下面
            if y < 0:
                y = cursor_y + 10
            
            # 确保窗口完全在屏幕内
            x = max(0, min(x, screen_width - window_width))
            y = max(0, min(y, screen_height - window_height))
            
            window.geometry(f"+{x}+{y}")
            
        except Exception as e:
            print(f"创建窗口失败: {e}")
            import traceback
            traceback.print_exc()

    def send_meme(self, url: str, window: tk.Tk):
        """发送表情包"""
        try:
            # 直接打开本地图片文件
            img = Image.open(url)
            output = BytesIO()
            img.convert('RGB').save(output, 'BMP')
            data = output.getvalue()[14:]
            output.close()
            
            # 复制到剪贴板
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, data)
            win32clipboard.CloseClipboard()
            
            # 关闭窗口
            window.destroy()
            
            # 等待一小段时间确保窗口已关闭
            time.sleep(0.1)
            
            # 模拟粘贴操作
            keyboard.press_and_release('ctrl+v')
            # 模拟回车发送
            time.sleep(0.1)
            keyboard.press_and_release('enter')
            
        except Exception as e:
            print(f"发送表情包失败: {e}") 

    def set_running_state(self, state: bool):
        """设置运行状态"""
        self.is_running = state
    
    def on_key(self, event):
        """按键事件处理"""
        if not self.is_running:
            return
            
        try:
            print(f"按键: {event.name}")
            
            if event.name == 'esc':
                if self.current_window and self.current_window.winfo_exists():
                    self.current_window.destroy()
                self.pinyin_buffer = ""
                
            elif event.name == 'backspace':
                self.pinyin_buffer = self.pinyin_buffer[:-1]
                print(f"拼音缓冲区: {self.pinyin_buffer}")
                
            elif event.name in ['space', 'enter']:
                if self.pinyin_buffer:
                    print(f"尝试获取中文文本，拼音: {self.pinyin_buffer}")
                    # 保存原始剪贴板内容
                    original_clipboard = None
                    try:
                        win32clipboard.OpenClipboard()
                        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                            original_clipboard = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                    except:
                        pass

                    # 模拟复制操作获取输入法转换的文本
                    keyboard.send('ctrl+a')
                    time.sleep(0.1)
                    keyboard.send('ctrl+c')
                    time.sleep(0.1)
                    
                    try:
                        win32clipboard.OpenClipboard()
                        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                            if text and any('\u4e00' <= char <= '\u9fff' for char in text):
                                print(f"获取到中文文本: {text}")
                                self.search_memes(text)
                        win32clipboard.EmptyClipboard()  # 清空剪贴板
                        
                        # 恢复原始剪贴板内容
                        if original_clipboard:
                            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, original_clipboard)
                        
                        win32clipboard.CloseClipboard()
                    except Exception as e:
                        print(f"获取剪贴板内容失败: {e}")
                        try:
                            win32clipboard.CloseClipboard()
                        except:
                            pass
                    
                    self.pinyin_buffer = ""
                    
            elif len(event.name) == 1:
                if event.name.isalpha():
                    self.pinyin_buffer += event.name
                    print(f"拼音缓冲区: {self.pinyin_buffer}")
                elif not event.name.isascii():
                    self.search_memes(event.name)
            
        except Exception as e:
            print(f"按键处理错误: {e}")

    def search_memes(self, text: str):
        """搜索表情包"""
        if not text.strip():
            return
            
        try:
            print(f"\n开始搜索: {text}")
            results = []
            
            # 生成搜索文本的繁简体版本
            search_text_simp = self.t2s.convert(text.lower())  # 简体版本
            search_text_trad = self.s2t.convert(text.lower())  # 繁体版本
            print(f"搜索文本: 简体「{search_text_simp}」繁体「{search_text_trad}」")
            
            # 分词处理
            search_words_simp = set(search_text_simp)  # 字符级分词
            search_words_trad = set(search_text_trad)
            
            for img in self.image_map:
                score = 0
                name = img['name'].lower()
                name_simp = self.t2s.convert(name)
                name_trad = self.s2t.convert(name)
                
                desc = img.get('description', '').lower()
                desc_simp = self.t2s.convert(desc)
                desc_trad = self.s2t.convert(desc)
                
                # 1. 完全匹配 (100分)
                if any(search_text in text for search_text, text in [
                    (search_text_simp, name_simp),
                    (search_text_simp, desc_simp),
                    (search_text_trad, name_trad),
                    (search_text_trad, desc_trad)
                ]):
                    score = 100
                
                # 2. 词组匹配 (80分)
                elif len(search_text_simp) > 1 and (
                    search_text_simp in name_simp or 
                    search_text_simp in desc_simp or
                    search_text_trad in name_trad or 
                    search_text_trad in desc_trad
                ):
                    score = 80
                
                # 3. 部分匹配
                else:
                    # 计算字符匹配率
                    name_chars = set(name_simp + name_trad)
                    desc_chars = set(desc_simp + desc_trad)
                    search_chars = search_words_simp | search_words_trad
                    
                    # 标题匹配 (最高60分)
                    name_match = len(search_chars & name_chars) / len(search_chars)
                    name_score = int(60 * name_match)
                    
                    # 描述匹配 (最高40分)
                    desc_match = len(search_chars & desc_chars) / len(search_chars)
                    desc_score = int(40 * desc_match)
                    
                    # 4. 标签加权 (额外20分)
                    tags_score = 0
                    if 'tags' in img:
                        tags = set(''.join(self.t2s.convert(tag.lower()) for tag in img['tags']))
                        tag_match = len(search_chars & tags) / len(search_chars)
                        tags_score = int(20 * tag_match)
                    
                    score = name_score + desc_score + tags_score
                
                # 5. 额外规则
                # 5.1 字数匹配加分
                if len(search_text_simp) == len(name_simp):
                    score += 10
                    
                # 5.2 位置权重
                if search_text_simp in name_simp[:len(search_text_simp)]:
                    score += 5  # 前缀匹配加分
                
                # 添加结果（分数超过阈值）
                if score >= self.config['features']['search']['score_threshold']:
                    results.append({
                        'url': str(self.images_path / img['file_name']),
                        'alt': img['name'],
                        'score': score,
                        'debug_info': {  # 调试信息
                            'name_match': name_match if 'name_match' in locals() else 1.0,
                            'desc_match': desc_match if 'desc_match' in locals() else 0.0,
                            'tags_score': tags_score if 'tags_score' in locals() else 0
                        }
                    })
            
            # 去重并排序
            unique_results = {}
            for result in results:
                url = result['url']
                if url not in unique_results or result['score'] > unique_results[url]['score']:
                    unique_results[url] = result
            
            results = list(unique_results.values())
            results.sort(key=lambda x: (-x['score'], x['alt']))  # 按分数降序，相同分数按名称排序
            
            print(f"找到 {len(results)} 个匹配结果")
            if results:
                print("排名前三的匹配：")
                for i, r in enumerate(results[:3], 1):
                    print(f"{i}. {r['alt']} (分数: {r['score']}, "
                          f"匹配率: {r['debug_info']['name_match']:.0%})")
            
            if results:
                if self.current_window and self.current_window.winfo_exists():
                    self.current_window.destroy()
                self.create_popup({'urls': results[:5]})
            else:
                print("未找到匹配的表情包")
            
        except Exception as e:
            print(f"搜索错误: {e}")
            import traceback
            traceback.print_exc()

    def load_image_map(self):
        """加载图片映射文件"""
        try:
            map_path = Path(__file__).parent.parent / 'data' / 'image_map.json'
            if not map_path.exists():
                print(f"警告: 图片映射文件不存在: {map_path}")
                return []
                
            with open(map_path, 'r', encoding='utf-8') as f:
                image_map = json.load(f)
                print(f"从 {map_path} 加载了 {len(image_map)} 个图片映射")
                return image_map
                
        except Exception as e:
            print(f"加载图片映射失败: {e}")
            return []

    def start(self):
        """启动监听"""
        print("\n=== 启动程序 ===")
        print("1. 启动键盘监听")
        keyboard.on_press(self.on_key)
        print("2. 创建主窗口")
        self.root = tk.Tk()
        self.root.withdraw()
        print("3. 启动主循环")
        self.root.mainloop() 