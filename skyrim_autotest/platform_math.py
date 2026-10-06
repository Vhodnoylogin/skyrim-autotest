"""Small measured-tracking coordinate solve; no requested pose-as-state shortcut."""
import math


def solve3(columns, value):
    rows = [[columns[c][r] for c in range(3)] + [value[r]] for r in range(3)]
    if any(not math.isfinite(v) for row in rows for v in row):
        raise ValueError('Nonfinite measured tracking transform')
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-5:
            raise ValueError('Tracking-to-skeleton transform is singular/unobserved')
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v/divisor for v in rows[col]]
        for row in range(3):
            if row != col:
                factor = rows[row][col]
                rows[row] = [a-factor*b for a,b in zip(rows[row], rows[col])]
    return [row[3] for row in rows]
