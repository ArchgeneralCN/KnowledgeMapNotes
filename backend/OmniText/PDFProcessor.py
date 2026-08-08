import base64
import camelot
import re
import pymupdf
import os
from typing import Union, List, Dict, Optional

# 兼容无tqdm环境
try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kwargs: x


class PDFProcessor:
    def __init__(self, output_dir: str = "output", image_dir: str = "images", vl_client=None):
        self.output_dir = output_dir
        self.image_dir = image_dir
        self.results = {}  # 存储结构：{filename: content_list}
        self.vl_client = vl_client
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.image_dir, exist_ok=True)

    #  base 64 编码格式
    def encode_image(self, image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r'\s+', ' ', text).strip() if isinstance(text, str) else text

    def _process_table_optimized(self, data):
        data = [row for row in data if any(cell.strip() for cell in row)]
        if not data:
            return data

        def process_row(row, is_header=False):
            new_row = []
            i = 0
            while i < len(row):
                cell = str(row[i]).strip()
                if is_header and '  ' in cell:
                    parts = re.split(r'\s{2,}', cell, maxsplit=1)
                    new_row.append(parts[0])
                    found = False
                    for j in range(i + 1, len(row)):
                        if str(row[j]).strip() == '':
                            new_row.append(parts[1])
                            i = j
                            found = True
                            break
                    if not found:
                        new_row.append(parts[1])
                else:
                    new_row.append(cell)
                i += 1
            return new_row

        processed_header = process_row(data[0], is_header=True)
        expected_columns = len(processed_header)
        final_data = [processed_header]

        for row in data[1:]:
            processed_row = process_row(row)
            if len(processed_row) < expected_columns:
                processed_row += [''] * (expected_columns - len(processed_row))
            else:
                processed_row = processed_row[:expected_columns]
            final_data.append(processed_row)

        for row in final_data:
            for i in range(len(row)):
                row[i] = re.sub(r'\s+', '', str(row[i]))
        return final_data

    @staticmethod
    def _is_empty_table(table_data):
        for row in table_data:
            for cell in row:
                if cell != '':
                    return False
        return True

    def _filter_empty_rows_cols(self, data):
        filtered_rows = [row for row in data if any(cell != '' for cell in row)]
        max_cols = max(len(row) for row in filtered_rows) if filtered_rows else 0
        uniform_data = [row + [''] * (max_cols - len(row)) for row in filtered_rows]
        transposed = list(zip(*uniform_data))
        filtered_cols = [col for col in transposed if any(cell != '' for cell in col)]
        result = list(zip(*filtered_cols)) if filtered_cols else []
        return [list(row) for row in result]

    def _process_tables(self, detailed_tables):
        filtered = self._filter_empty_rows_cols(detailed_tables)
        if not filtered:
            return "<table></table>"

        markdown = "| " + " | ".join(filtered[0]) + " |\n"
        for row in filtered[1:]:
            markdown += "| " + " | ".join(row) + " |\n"
        return f"<table>\n{markdown}</table>"

    def _extract_images(self, page, page_num):
        image_info_list = []
        image_blocks = page.get_images(full=True)

        for img in image_blocks:
            xref = img[0]
            base_image = page.parent.extract_image(xref)
            image_ext = base_image["ext"]
            image_data = base_image["image"]
            # TODO 可能多文件图片名会冲突，建议再加上文件名
            image_filename = f"page_{page_num + 1}_img_{xref}.{image_ext}"
            image_path = os.path.join(self.image_dir, image_filename)

            with open(image_path, "wb") as img_file:
                img_file.write(image_data)

            image_rects = page.get_image_rects(xref)
            for rect in image_rects:
                adj_bbox = (
                    max(0, rect.x0 - 2),
                    max(0, rect.y1 - 2),
                    min(page.rect.width, rect.x1 + 2),
                    min(page.rect.height, rect.y0 + 2)
                )
                image_info_list.append({
                    "path": image_path,
                    "bbox": adj_bbox
                })

        return image_info_list

    def _process_pdf(self, pdf_path: str, use_img2txt: bool = False) -> List[str]:
        # 确保use_img2txt是布尔类型
        if isinstance(use_img2txt, str):
            use_img2txt_str = use_img2txt.lower().strip()
            use_img2txt = use_img2txt_str == 'open' or use_img2txt_str == 'true' or use_img2txt_str == '1' or use_img2txt_str == 'yes'
        else:
            use_img2txt = bool(use_img2txt)

        tqdm.write(f"处理PDF {os.path.basename(pdf_path)} 使用图片文本识别: {use_img2txt}")

        try:
            tables = camelot.read_pdf(pdf_path, pages='all', flavor='lattice')
        except Exception as e:
            tqdm.write(f"无法提取表格: {str(e)}")
            tables = []  # 使用空列表表示无法提取表格

        try:
            doc = pymupdf.open(pdf_path)
        except Exception as e:
            tqdm.write(f"无法打开PDF文件: {str(e)}")
            return [f"无法处理文件 {os.path.basename(pdf_path)}: {str(e)}"]

        full_content = []
        table_meta = []

        if tables and len(tables) > 0:
            for idx, table in enumerate(tables):
                try:
                    page_num = int(table.parsing_report['page']) - 1
                    x1, y1, x2, y2 = table._bbox
                    table_meta.append({
                        "page": page_num,
                        "bbox": (x1, y1, x2, y2),
                        "index": idx
                    })
                except Exception as e:
                    tqdm.write(f"处理表格信息失败: {str(e)}")
                    # 继续处理下一个表格

        # 添加页面处理进度条
        with tqdm(total=len(doc), desc=f"处理 {os.path.basename(pdf_path)}",
                  leave=False, unit='page') as page_pbar:
            for page_num in range(len(doc)):
                try:
                    page = doc.load_page(page_num)
                    page_rect = page.rect
                    page_height = page_rect.height

                    current_tables = []
                    for table in table_meta:
                        if table["page"] == page_num:
                            x1, y1, x2, y2 = table["bbox"]
                            fitz_bbox = (
                                x1,
                                page_height - y2,
                                x2,
                                page_height - y1
                            )
                            current_tables.append({
                                "fitz_bbox": fitz_bbox,
                                "index": table["index"]
                            })

                    try:
                        text_blocks = page.get_text("blocks")
                    except Exception as e:
                        tqdm.write(f"页面 {page_num + 1} 文本提取失败: {str(e)}")
                        text_blocks = []

                    try:
                        image_blocks = self._extract_images(page, page_num)
                    except Exception as e:
                        tqdm.write(f"页面 {page_num + 1} 图像提取失败: {str(e)}")
                        image_blocks = []

                    all_blocks = []
                    for block in text_blocks:
                        all_blocks.append({
                            "type": "text",
                            "bbox": (block[0], block[1], block[2], block[3]),
                            "content": self._clean_text(block[4])
                        })
                    for img in image_blocks:
                        all_blocks.append({
                            "type": "image",
                            "bbox": img["bbox"],
                            "content": f"<image>{img['path']}</image>"
                        })

                    all_blocks.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))

                    processed_tables = set()
                    for block in all_blocks:
                        block_bbox = block["bbox"]

                        if block_bbox[1] < page_rect.height * 0.07:
                            continue

                        in_table = False
                        for table in sorted(current_tables, key=lambda t: t["fitz_bbox"][1]):
                            t_bbox = table["fitz_bbox"]
                            if (block_bbox[0] >= t_bbox[0] and
                                    block_bbox[2] <= t_bbox[2] and
                                    block_bbox[1] >= t_bbox[1] and
                                    block_bbox[3] <= t_bbox[3]):
                                if table["index"] not in processed_tables:
                                    full_content.append({"type": "table", "index": table["index"]})
                                    processed_tables.add(table["index"])
                                in_table = True
                                break

                        if not in_table:
                            if block["type"] == "text" and block["content"]:
                                full_content.append({
                                    "type": "text",
                                    "content": block["content"]
                                })
                            elif block["type"] == "image":
                                full_content.append({
                                    "type": "image",
                                    "content": block["content"]
                                })
                except Exception as e:
                    tqdm.write(f"处理页面 {page_num + 1} 时出错: {str(e)}")
                    full_content.append({
                        "type": "text",
                        "content": f"[页面 {page_num + 1} 处理失败: {str(e)}]"
                    })
                finally:
                    page_pbar.update(1)

        final_output = []
        table_index = 0
        for item in full_content:
            if item["type"] == "text":
                final_output.append(item["content"])
            elif item["type"] == "image":
                if use_img2txt and self.vl_client is not None:
                    # 对图片进行多模态处理
                    try:
                        # print(item["content"])
                        input_string = item["content"]
                        content = re.search(r'<image>(.*?)</image>', input_string).group(1)
                        # 获取文件类型
                        file_type = content.split('.')[-1].lower()
                        # 将xxxx/test.png替换为你本地图像的绝对路径
                        base64_image = self.encode_image(content)
                        completion = self.vl_client.chat.completions.create(
                            model="qwen-vl-max-latest",
                            messages=[
                                {
                                    "role": "system",
                                    "content": [{"type": "text", "text": "You are a helpful assistant."}]},
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "image_url",
                                            # 需要注意，传入Base64，图像格式（即image/{format}）需要与支持的图片列表中的Content Type保持一致。"f"是字符串格式化的方法。
                                            # PNG图像：  f"data:image/png;base64,{base64_image}"
                                            # JPEG图像： f"data:image/jpeg;base64,{base64_image}"
                                            # WEBP图像： f"data:image/webp;base64,{base64_image}"
                                            "image_url": {"url": f"data:image/{file_type};base64,{base64_image}"},
                                        },
                                        {"type": "text", "text": '''
                                                    你是一个笔记图像理解助手，图片表达了什么? 请遵循以下指南：
                                                    - 不要解释任何图中文字的概念
                                                    - 用最简练的话告诉我图像的主要内容
                                                    - 如果是图表请告诉我表的数据
                                                    - 告诉我图片类型就不要继续解释这类图片的特点了，例如：知识图谱，照片，柱状图，表格等
                                                    '''},
                                    ],
                                }
                            ],
                        )
                        img_dcs = completion.choices[0].message.content
                        result = f'<image>{img_dcs}</image>'
                    except Exception as e:
                        tqdm.write(f"图片处理失败: {str(e)}")
                        # 如果处理失败，回退到不处理图片
                        result = item["content"]
                else:
                    result = item["content"]

                final_output.append(result)
            elif item["type"] == "table":
                if tables and table_index < len(tables):
                    try:
                        table = tables[table_index]
                        processed = self._process_table_optimized(table.data)
                        if not self._is_empty_table(processed):
                            final_output.append(self._process_tables(processed))
                        else:
                            final_output.append("<table>表格解析失败</table>")
                        table_index += 1
                    except Exception as e:
                        tqdm.write(f"处理表格索引 {table_index} 失败: {str(e)}")
                        final_output.append("<table>表格解析出错</table>")
                        table_index += 1

        if not final_output:
            # 如果没有成功提取任何内容，返回一个错误信息
            return [f"无法从文件 {os.path.basename(pdf_path)} 提取有效内容"]

        return final_output

    def process(self, pdf_files: Union[str, List[str]], use_img2txt=False):
        """处理多个PDF文件"""
        # 确保use_img2txt是布尔类型
        if isinstance(use_img2txt, str):
            use_img2txt_str = use_img2txt.lower().strip()
            use_img2txt = use_img2txt_str == 'open' or use_img2txt_str == 'true' or use_img2txt_str == '1' or use_img2txt_str == 'yes'
        else:
            use_img2txt = bool(use_img2txt)

        tqdm.write(f"PDF处理器使用图片文本识别: {use_img2txt}")

        if isinstance(pdf_files, str):
            pdf_files = [pdf_files]

        valid_files = []
        missing_files = []
        for path in pdf_files:
            if os.path.exists(path):
                if path.lower().endswith('.pdf'):
                    valid_files.append(path)
                else:
                    tqdm.write(f"文件类型错误: {path} (非PDF文件)")
            else:
                missing_files.append(path)

        if missing_files:
            tqdm.write("\n以下文件不存在，已跳过处理:")
            for f in missing_files:
                tqdm.write(f"  - {f}")

        with tqdm(total=len(valid_files), desc="总进度", unit="file") as main_pbar:
            for pdf_path in valid_files:
                try:
                    if not os.path.exists(pdf_path):
                        tqdm.write(f"文件突然不可访问: {pdf_path}")
                        continue

                    try:
                        with open(pdf_path, 'rb') as f:
                            # 检查文件头部是否为有效的PDF文件
                            header = f.read(5)
                            if header != b'%PDF-':
                                tqdm.write(f"无效的PDF文件: {pdf_path} (头部格式不正确)")
                                continue
                    except PermissionError:
                        tqdm.write(f"文件无读取权限: {pdf_path}")
                        continue
                    except Exception as e:
                        tqdm.write(f"读取文件时出错: {pdf_path}, 错误: {str(e)}")
                        continue

                    try:
                        content = self._process_pdf(pdf_path, use_img2txt)
                        filename = os.path.basename(pdf_path)
                        self.results[filename] = content
                        main_pbar.set_postfix(file=filename[:15])
                    except Exception as e:
                        tqdm.write(f"\n处理PDF内容时出错: {pdf_path}, 错误: {str(e)}")
                except Exception as e:
                    tqdm.write(f"\n处理文件 {pdf_path} 时出错: {str(e)}")
                finally:
                    main_pbar.update(1)

    def save_as_txt(self, combine: bool = False, output_path: Optional[str] = None):
        """
        保存处理结果到文本文件
        :param combine: 是否合并所有文件结果
        :param output_path: 自定义输出路径（combine=True时为完整路径，combine=False时为文件名）
        """
        if not self.results:
            print("没有可保存的结果")
            return

        if combine:
            # 合并保存逻辑
            combined = []
            for filename, content in self.results.items():
                combined.append(f"\n{'=' * 20} {filename} {'=' * 20}\n")
                combined.extend(content)

            final_path = output_path or os.path.join(self.output_dir, "combined_output.txt")
            with open(final_path, "w", encoding="utf-8") as f:
                f.write("\n".join(combined))
            print(f"合并保存到: {final_path}")
        else:
            # 分文件保存逻辑
            for filename, content in self.results.items():
                if output_path:
                    # 使用指定的输出路径
                    # 如果output_path是完整路径，则直接使用
                    if os.path.dirname(output_path):
                        final_path = output_path
                    # 如果output_path只是文件名，则拼接输出目录
                    else:
                        final_path = os.path.join(self.output_dir, output_path)
                else:
                    # 使用默认命名规则
                    final_path = os.path.join(self.output_dir, f"{os.path.splitext(filename)[0]}.txt")

                with open(final_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(content))
                print(f"保存到: {final_path}")

    def get_output(self, combine: bool = False) -> Union[str, Dict[str, str]]:
        """
        获取处理结果
        :param combine: 是否合并所有文件结果
        :return: 合并时返回字符串，否则返回{文件名: 内容}字典
        """
        if not self.results:
            return "" if combine else {}

        if combine:
            combined = []
            for filename, content in self.results.items():
                combined.append(f"\n{'=' * 20} {filename} {'=' * 20}\n")
                combined.extend(content)
            return "\n".join(combined)
        else:
            return {filename: "\n".join(content) for filename, content in self.results.items()}
