from deep_analyse import *

result = get_basic_result('78-80')

res_sorted = result.sort_values(by=result[0], ascending=True)

print(res_sorted)