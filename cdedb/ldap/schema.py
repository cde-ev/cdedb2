"""Process information about ldap schemas from specification files."""

from typing import List

from ldaptor.schema import AttributeTypeDescription, ObjectClassDescription


class SchemaDescription:
    """Process all information provided by an LDAP schema.

    This is a slight wrapper to handle various definitions in the same file. Those are
    for example provided by the openldap project.

    For processing the entries of the schema, the `ldaptor.schema` classes are used.
    """
    attribute_types: List[bytes]
    matching_rules: List[bytes]
    object_classes: List[bytes]
    syntaxes: List[bytes]

    def __init__(self, file: str) -> None:
        self.attribute_types = []
        self.matching_rules = []
        self.object_classes = []
        self.syntaxes = []
        for block in self.split_file(file):
            self.process_chunk(block)

    @staticmethod
    def split_file(file: str) -> List[str]:
        """Split a given file into blocks separated by whitespace."""
        lines = file.split(sep="\n")

        # next, group all blocks separated by one or more blank lines together
        blocks: List[List[str]] = []
        block: List[str] = []
        for line in lines:
            if line.startswith("#"):
                continue
            if line.strip() == "":
                if block:
                    blocks.append(block)
                    block = []
            else:
                block.append(line)

        # at last, join the lines of the individual blocks
        file_blocks = ["\n".join(block) for block in blocks]
        return file_blocks

    def process_chunk(self, block: str) -> None:
        """Process a block describing a single entry of the schema."""
        if block.startswith("attributetype"):
            asn_str = block.lstrip("attributetype").strip()
            self.attribute_types.append(AttributeTypeDescription(asn_str).toWire())
        elif block.startswith("objectclass"):
            asn_str = block.lstrip("objectclass").strip()
            self.object_classes.append(ObjectClassDescription(asn_str).toWire())
        else:
            raise ValueError(f"Cant process the following chunk:\n{block}")
