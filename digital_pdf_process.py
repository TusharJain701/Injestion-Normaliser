import pymupdf

def read_digital_pdf(pdf_path: str) -> str:

    """ Extract all text from a digital PDF, including tables. """

    # Step 1: Opening the PDF
    doc = pymupdf.open(pdf_path)
    all_text = []

    # Step 2: Reading the text of each page
    for page in doc:
        all_text.append(page.get_text())

        # Step 3: Finding tables on the page (empty list if there are none) and adding them as markdown
        for table in page.find_tables().tables:
            all_text.append(table.to_markdown())

    # Step 4: Closing the PDF
    doc.close()

    # Step 5: Joining all pages into one string and returning it
    return "\n".join(all_text)


# It takes a PDF path in and gives all the text back, with tables as markdown.