from typing import List

from ldaptor.schema import AttributeTypeDescription, ObjectClassDescription


class SchemaDescription:
    """Process all information provided by an LDAP schema.

    This is a slight wrapper to handle various definitions in the same file. Those are
    for example provided by the openldap project.

    For processing the entries of the schema, the `ldaptor.schema` classes are used.
    """
    attribute_types = list()
    matching_rules = list()
    object_classes = list()
    syntaxes = list()

    def __init__(self, file: str) -> None:
        for block in self.chunk_file(file):
            self.process_chunk(block)

    @staticmethod
    def chunk_file(file: str) -> List[str]:
        """Split a given file into blocks separated by whitespace."""
        lines = file.split(sep="\n")

        # first, strip all comments
        lines = [line for line in lines if not line.startswith("#")]

        # next, group all blocks separated by one or more blank lines together
        blocks = list()
        block = list()
        for line in lines:
            if line.strip() == "":
                if block:
                    blocks.append(block)
                    block = list()
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
