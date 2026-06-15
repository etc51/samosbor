from __future__ import annotations


def build_offline_autonomy_config_text(source_text: str, *, parquet_dir_path: str) -> str:
    lines = source_text.splitlines()
    output: list[str] = []
    in_data_section = False
    saw_data_section = False
    wrote_source = False
    wrote_parquet_dir = False

    def flush_data_defaults() -> None:
        nonlocal wrote_source, wrote_parquet_dir
        if not wrote_source:
            output.append('source = "parquet-directory"')
            wrote_source = True
        if not wrote_parquet_dir:
            output.append(f'parquet_dir_path = "{parquet_dir_path}"')
            wrote_parquet_dir = True

    for line in lines:
        stripped = line.strip()
        is_section_header = stripped.startswith("[") and stripped.endswith("]")
        if is_section_header:
            if in_data_section:
                flush_data_defaults()
            in_data_section = stripped == "[data]"
            if in_data_section:
                saw_data_section = True
                wrote_source = False
                wrote_parquet_dir = False
            output.append(line)
            continue

        if in_data_section:
            if stripped.startswith("source ="):
                output.append('source = "parquet-directory"')
                wrote_source = True
                continue
            if stripped.startswith("parquet_dir_path ="):
                output.append(f'parquet_dir_path = "{parquet_dir_path}"')
                wrote_parquet_dir = True
                continue
            if stripped.startswith("csv_path =") or stripped.startswith("local_data_pack_path ="):
                continue

        output.append(line)

    if in_data_section:
        flush_data_defaults()

    if not saw_data_section:
        raise ValueError("Config text is missing a [data] section.")

    return "\n".join(output).rstrip() + "\n"
