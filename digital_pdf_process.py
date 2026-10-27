import pymupdf


def _clean(text) -> str:
    return " ".join(str(text).split()) if text is not None else ""


def _table_rows(page, table) -> list:

    """
    Read every cell straight from the page (by position), so that numbers such as 1,500.00
    come out exactly as printed. Falls back to the table finder's own text if that fails.
    """

    try:
        rows = []
        for row in table.rows:
            rows.append([
                _clean(page.get_text("text", clip=pymupdf.Rect(cell))) if cell is not None else ""
                for cell in row.cells
            ])
        return rows
    except Exception:
        return [[_clean(c) for c in row] for row in table.extract()]


def read_tables(page) -> list:

    """ Tables on a digital PDF page, as lists of rows (each row is a list of cell texts). """

    tables = []
    try:
        for table in page.find_tables().tables:
            rows = [r for r in _table_rows(page, table) if any(r)]       # drop empty rows
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:        # a single row or column is not a table
                tables.append(rows)
    except Exception:
        pass   # a page that confuses the table finder still keeps its normal text
    return tables


# It takes a PDF page in and gives the tables on it back.
