

def load_json_data(filepath):
    """
    读取 json / jsonl / jl 文件，统一返回列表数据。

    :param filepath: 输入文件路径
    :return: list
    """
    import json

    with open(filepath, "r", encoding="utf-8") as file:
        content = file.read().strip()

    if not content:
        return []

    if content[0] == "[":
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    obj_list = []
    for line in content.splitlines():
        line = line.strip().strip(",")
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, list):
                obj_list.extend(data)
            else:
                obj_list.append(data)
        except Exception as e:
            print(f"解析 JSON 行时出错: {line}, 错误: {e}")
    return obj_list


def data2excel(
    obj_list,
    output_filepath,
    drop_duplicates_subset=None,
    exclude_columns=None,
):
    """
    将 json 数据列表转换为 Excel。

    :param obj_list: json 数据列表
    :param output_filepath: Excel 输出路径
    :param drop_duplicates_subset: 用于去重的列名列表，例如 ['链接']
    :param exclude_columns: 导出时需要排除的列名列表，例如 ['原始文本列表']
    :return: pandas.DataFrame
    """
    import pandas as pd

    df = pd.DataFrame(obj_list)

    if drop_duplicates_subset is not None and not df.empty:
        # 只保留实际存在于 DataFrame 中的列进行去重，防止报错
        valid_subset = [col for col in drop_duplicates_subset if col in df.columns]
        if valid_subset:
            original_len = len(df)

            # 对重复键按非空字段数量排序，优先保留信息更完整的记录。
            df["non_null_count"] = df.notna().sum(axis=1)
            df = df.sort_values("non_null_count", ascending=False)
            df = df.groupby(valid_subset, as_index=False).first()
            df = df.drop(columns=["non_null_count"])

            print(
                f"基于列 {valid_subset} 去重并合并属性，去重前 {original_len} 条，去重后 {len(df)} 条。"
            )
        else:
            print(
                f"警告：指定的去重列 {drop_duplicates_subset} 不存在于数据中，跳过去重。"
            )

    if exclude_columns and not df.empty:
        valid_exclude_columns = [col for col in exclude_columns if col in df.columns]
        if valid_exclude_columns:
            df = df.drop(columns=valid_exclude_columns)
            print(f"已排除列: {valid_exclude_columns}")
        else:
            print(f"警告：指定的排除列 {exclude_columns} 不存在于数据中，跳过排除。")

    df.to_excel(output_filepath, index=False)
    print(f"Excel 文件已保存：{output_filepath}")
    return df


def json2excel(
    filepath,
    drop_duplicates_subset=None,
    exclude_columns=None,
    output_filepath=None,
    output_filename=None,
):
    """
    兼容旧调用：读取 json/jl 文件并输出同名 Excel。

    :param filepath: JSON/JL 文件路径
    :param drop_duplicates_subset: 用于去重的列名列表，例如 ['链接']
    :param exclude_columns: 导出时需要排除的列名列表，例如 ['原始文本列表']
    :param output_filepath: 可选的 Excel 输出路径；可单独传完整路径，也可与 output_filename 组合使用目录
    :param output_filename: 可选的 Excel 输出文件名；可单独传文件名，也可与 output_filepath 组合覆盖默认文件名
    :return:
    """
    import os

    default_folder_path = os.path.dirname(filepath)
    default_file_name = f"{os.path.splitext(os.path.basename(filepath))[0]}.xlsx"

    if output_filepath:
        output_folder_path = os.path.dirname(output_filepath) or default_folder_path
        output_file_name = os.path.basename(output_filepath) or default_file_name
    else:
        output_folder_path = default_folder_path
        output_file_name = default_file_name

    if output_filename:
        output_file_name = output_filename

    output_filepath = os.path.join(output_folder_path, output_file_name)
    obj_list = load_json_data(filepath)
    data2excel(
        obj_list,
        output_filepath,
        drop_duplicates_subset=drop_duplicates_subset,
        exclude_columns=exclude_columns,
    )

if __name__ == "__main__":
    print(1)