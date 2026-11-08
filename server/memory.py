"""Historical RAM sizes derived only from the corresponding report."""
RAM_USED_SQL = """COALESCE(json_extract(data,'$.system.memory_used_bytes'),
 CASE WHEN json_extract(data,'$.system.memory_total_bytes')>0 THEN
 CASE WHEN json_extract(data,'$.system.memory_available_bytes') IS NOT NULL
 THEN MAX(0,json_extract(data,'$.system.memory_total_bytes')-json_extract(data,'$.system.memory_available_bytes'))
 ELSE json_extract(data,'$.system.memory_total_bytes')*json_extract(data,'$.memory_percent')/100.0 END END)"""
RAM_TOTAL_SQL = "NULLIF(json_extract(data,'$.system.memory_total_bytes'),0)"


def memory_tooltip(point):
    from .dashboard import size
    point=dict(point)
    used=point.get('ram_used_bytes')
    if used is None:return 'объём RAM недоступен в этом отчёте'
    result='занято '+size(used)
    if point.get('ram_total_bytes'):result+=' из '+size(point['ram_total_bytes'])
    return result
