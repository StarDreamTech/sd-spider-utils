import json
from pathlib import Path


def load_json_data(filepath) -> list:
    """读取 JSON 或 JSONL 文件，并统一返回列表。

    :param filepath: JSON、JSONL 或 JL 文件路径
    :return: 文件中的对象列表
    :raises ValueError: JSONL 中存在无效行时抛出
    """
    content = Path(filepath).read_text(encoding="utf-8").strip()
    if not content:
        return []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = []
        for line_number, line in enumerate(content.splitlines(), 1):
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                item = json.loads(line)
                data.extend(item if isinstance(item, list) else [item])
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON") from exc
        return data

    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


def data2excel(
    obj_list,
    output_filepath,
    drop_duplicates_subset=None,
    exclude_columns=None,
):
    """把字典列表写入 Excel，可按指定列去重或排除列。

    :param obj_list: 待导出的字典列表
    :param output_filepath: Excel 输出路径
    :param drop_duplicates_subset: 用于去重的列名列表
    :param exclude_columns: 导出时排除的列名列表
    :return: 导出后的 pandas.DataFrame
    """
    import pandas as pd

    dataframe = pd.DataFrame(obj_list)
    if drop_duplicates_subset and not dataframe.empty:
        subset = [
            column for column in drop_duplicates_subset if column in dataframe.columns
        ]
        if subset:
            # 信息较完整的重复记录优先。
            order = dataframe.notna().sum(axis=1).sort_values(ascending=False).index
            dataframe = (
                dataframe.loc[order]
                .groupby(subset, as_index=False, dropna=False)
                .first()
            )

    if exclude_columns and not dataframe.empty:
        columns = [column for column in exclude_columns if column in dataframe.columns]
        if columns:
            dataframe = dataframe.drop(columns=columns)

    dataframe.to_excel(output_filepath, index=False)
    return dataframe


def json2excel(
    filepath,
    drop_duplicates_subset=None,
    exclude_columns=None,
    output_filepath=None,
    output_filename=None,
):
    """读取 JSON/JSONL 文件并写入 Excel，默认与源文件同名。

    :param filepath: JSON、JSONL 或 JL 文件路径
    :param drop_duplicates_subset: 用于去重的列名列表
    :param exclude_columns: 导出时排除的列名列表
    :param output_filepath: 可选的 Excel 输出路径
    :param output_filename: 可选的 Excel 输出文件名
    :return: 导出后的 pandas.DataFrame
    """
    source = Path(filepath)
    output = Path(output_filepath) if output_filepath else source.with_suffix(".xlsx")
    if output_filename:
        output = output.parent / output_filename
    return data2excel(
        load_json_data(source),
        output,
        drop_duplicates_subset=drop_duplicates_subset,
        exclude_columns=exclude_columns,
    )
