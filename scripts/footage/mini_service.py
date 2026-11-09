"""One uploader/index pass, launched directly by Python on the Mac mini."""
import sys

import dataset_index
import upload_footage


def main():
    upload_status = upload_footage.main(["--once"])
    index_status = dataset_index.main([])
    return upload_status or index_status


if __name__ == "__main__":
    sys.exit(main())
