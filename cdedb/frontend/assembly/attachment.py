#!/usr/bin/env python3

"""Services for the assembly realm."""

import pathlib
from typing import Optional

import werkzeug.exceptions
from schulze_condorcet.types import Candidate
from werkzeug import Response

import cdedb.common.validation.types as vtypes
from cdedb.common import CdEDBObject, RequestState, get_hash, merge_dicts
from cdedb.common.n_ import n_
from cdedb.common.sorting import xsorted
from cdedb.frontend.assembly.base import AssemblyBaseFrontend
from cdedb.frontend.common import (
    REQUESTdata, REQUESTfile, access, assembly_guard, check_validation as check,
)

#: Magic value to signal abstention during _classical_ voting.
#: This can not occur as a shortname since it contains forbidden characters.
MAGIC_ABSTAIN = Candidate("special: abstain")

ASSEMBLY_BAR_ABBREVIATION = "#"


class AssemblyAttachmentMixin(AssemblyBaseFrontend):
    """Organize congregations and vote on ballots."""
    realm = "assembly"

    @access("assembly")
    def list_attachments(self, rs: RequestState, assembly_id: int) -> Response:
        """Render form."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            rs.notify("error", n_("May not access attachments for this assembly."))
            return self.redirect(rs, "assembly/index")
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attachments_versions = self.assemblyproxy.get_attachments_versions(
            rs, attachment_ids)

        def sortkey(att: CdEDBObject) -> tuple[str, int]:
            """This is an inline function and not in EntitySorter since its only used
            here and needs some extra context."""
            latest_version = attachments_versions[att["id"]][att["latest_version_nr"]]
            return latest_version["title"], att["id"]

        sorted_attachments = {
            att["id"]: att for att in xsorted(attachments.values(), key=sortkey)}
        are_attachment_versions_creatable = \
            self.assemblyproxy.are_attachment_versions_creatable(rs, attachment_ids)
        are_attachment_versions_deletable = \
            self.assemblyproxy.are_attachment_versions_deletable(rs, attachment_ids)
        are_attachments_deletable = {
            attachment_id: (attachment["num_versions"] <= 1
                            and are_attachment_versions_deletable[attachment_id])
            for attachment_id, attachment in attachments.items()}
        return self.render(rs, "attachment/list_attachments", {
            "attachments": sorted_attachments,
            "attachments_versions": attachments_versions,
            "are_attachment_versions_creatable": are_attachment_versions_creatable,
            "are_attachment_versions_deletable": are_attachment_versions_deletable,
            "are_attachments_deletable": are_attachments_deletable,
        })

    @access("assembly")
    def get_attachment(self, rs: RequestState, assembly_id: int,
                       attachment_id: int) -> Response:
        """A wrapper around get_attachment_version to retrieve the current version."""
        attachment = self.assemblyproxy.get_attachment(rs, attachment_id)
        # Access checking is done inside get_attachment_version
        return self.redirect(rs, "assembly/get_attachment_version",
                             params={"version_nr": attachment["latest_version_nr"]})

    @access("assembly")
    @REQUESTdata("version_nr")
    def get_attachment_version(self, rs: RequestState, assembly_id: int,
                               attachment_id: int, version_nr: int) -> Response:
        """Retrieve the content of a given attachment version."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        versions = self.assemblyproxy.get_attachment_versions(rs, attachment_id)
        content = self.assemblyproxy.get_attachment_content(
            rs, attachment_id, version_nr)
        if not content:
            rs.notify("error", n_("File not found."))
            return self.redirect(rs, "assembly/list_attachments")
        return self.send_file(rs, data=content, mimetype="application/pdf",
                              filename=versions[version_nr]['filename'])

    @access("assembly")
    @assembly_guard
    def add_attachment_form(self, rs: RequestState, assembly_id: int) -> Response:
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify('error',
                      n_("Cannot add attachment once the assembly has been locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        return self.render(rs, "attachment/add_attachment")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("title", "authors", "filename")
    @REQUESTfile("attachment")
    def add_attachment(self, rs: RequestState, assembly_id: int,
                       attachment: werkzeug.datastructures.FileStorage,
                       title: str, filename: Optional[vtypes.Identifier],
                       authors: Optional[str]) -> Response:
        """Create a new attachment."""
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify('error',
                      n_("Cannot add attachment once the assembly has been locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        if attachment and not filename:
            assert attachment.filename is not None
            tmp = pathlib.Path(attachment.filename).parts[-1]
            filename = check(rs, vtypes.Identifier, tmp, 'filename')
        attachment = check(rs, vtypes.PDFFile, attachment, 'attachment')
        if rs.has_validation_errors():
            return self.add_attachment_form(rs, assembly_id=assembly_id)
        assert attachment is not None
        data: CdEDBObject = {
            "title": title,
            "assembly_id": assembly_id,
            "filename": filename,
            "authors": authors,
        }
        code = self.assemblyproxy.add_attachment(rs, data, attachment)
        rs.notify_return_code(code, success=n_("Attachment added."))
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("attachment_ack_delete")
    def delete_attachment(self, rs: RequestState, assembly_id: int,
                          attachment_id: int, attachment_ack_delete: bool) -> Response:
        """Delete an attachment."""
        if not attachment_ack_delete:
            rs.append_validation_error(
                ("attachment_ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/list_attachments")

        if not self.assemblyproxy.is_attachment_version_deletable(rs, attachment_id):
            rs.notify("error", n_("Attachment can not be deleted."))
            return self.redirect(rs, "assembly/list_attachments")

        attachment = self.assemblyproxy.get_attachment(rs, attachment_id)
        # This is possible in theory but should not be done to avoid user errors
        if attachment['num_versions'] > 1:
            rs.notify("error", n_("Remove all but the last version before deleting the"
                                  " attachment."))
            return self.redirect(rs, "assembly/list_attachments")

        cascade = {"ballots", "versions"}
        code = self.assemblyproxy.delete_attachment(rs, attachment_id, cascade)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly")
    @assembly_guard
    def add_attachment_version_form(self, rs: RequestState, assembly_id: int,
                                    attachment_id: int) -> Response:
        """Render form."""
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        if not self.assemblyproxy.is_attachment_version_creatable(rs, attachment_id):
            rs.notify('error',
                      n_("Cannot add attachment version once the assembly has been"
                         " locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        latest_version = self.assemblyproxy.get_latest_attachment_version(
            rs, attachment_id)
        is_deletable = self.assemblyproxy.is_attachment_version_deletable(
            rs, attachment_id)

        # Prefill information, if possible and untouched
        for metadatum in {'title', 'authors', 'filename'}:
            if metadatum not in rs.values:
                rs.values[metadatum] = latest_version[metadatum]

        return self.render(
            rs, "attachment/configure_attachment_version", {
                'latest_version': latest_version,
                'is_deletable': is_deletable
            })

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("title", "authors", "filename", "ack_creation")
    @REQUESTfile("attachment")
    def add_attachment_version(self, rs: RequestState, assembly_id: int,
                               attachment_id: int,
                               attachment: werkzeug.datastructures.FileStorage,
                               title: str, filename: Optional[vtypes.Identifier],
                               authors: Optional[str],
                               ack_creation: bool = None) -> Response:
        """Create a new version of an existing attachment.

        If this version can not be deleted afterwards, the creation must be confirmed.
        """
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        if not self.assemblyproxy.is_attachment_version_creatable(rs, attachment_id):
            rs.ignore_validation_errors()
            rs.notify('error',
                      n_("Cannot add attachment version once the assembly has been"
                         " locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        if attachment and not filename:
            assert attachment.filename is not None
            tmp = pathlib.Path(attachment.filename).parts[-1]
            filename = check(rs, vtypes.Identifier, tmp, 'filename')
        attachment = check(rs, vtypes.PDFFile, attachment, 'attachment')
        is_deletable = self.assemblyproxy.is_attachment_version_deletable(rs,
                                                                          attachment_id)
        if not is_deletable and not ack_creation:
            rs.append_validation_error(
                ("ack_creation", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.add_attachment_version_form(
                rs, assembly_id=assembly_id, attachment_id=attachment_id)
        assert attachment is not None
        data: CdEDBObject = {
            'title': title,
            'filename': filename,
            'authors': authors,
        }
        versions = self.assemblyproxy.get_attachment_versions(rs, attachment_id)
        file_hash = get_hash(attachment)
        if any(v["file_hash"] == file_hash for v in versions.values()):
            # TODO maybe display some kind of warning here?
            # Currently this would mean that you need to reupload the file.
            pass

        data['attachment_id'] = attachment_id
        code = self.assemblyproxy.add_attachment_version(rs, data, attachment)
        rs.notify_return_code(code, success=n_("Attachment added."))
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly")
    @assembly_guard
    def change_attachment_version_form(self, rs: RequestState, assembly_id: int,
                                       attachment_id: int, version_nr: int) -> Response:
        """Render form."""
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        if not self.assemblyproxy.is_attachment_version_deletable(rs, attachment_id):
            rs.notify("error", n_("Attachment version can not be changed."))
            return self.redirect(rs, "assembly/list_attachments")
        latest_version = self.assemblyproxy.get_latest_attachment_version(
            rs, attachment_id)
        merge_dicts(rs.values, rs.ambience['attachment_version'])
        return self.render(
            rs, "attachment/configure_attachment_version", {
                'latest_version': latest_version,
                'is_deletable': True
            })

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("title", "authors", "filename")
    def change_attachment_version(self, rs: RequestState, assembly_id: int,
                               attachment_id: int, version_nr: int,
                               title: str, filename: Optional[vtypes.Identifier],
                               authors: Optional[str]) -> Response:
        """Change the metadata of a new version of an existing attachment."""
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        if not self.assemblyproxy.is_attachment_version_deletable(rs, attachment_id):
            rs.notify("error", n_("Attachment version can not be changed."))
            return self.redirect(rs, "assembly/attachment/list_attachments")
        if rs.has_validation_errors():
            return self.change_attachment_version_form(
                rs, assembly_id=assembly_id, attachment_id=attachment_id,
                version_nr=version_nr)
        data: CdEDBObject = {
            'attachment_id': attachment_id,
            'version_nr': version_nr,
            'title': title,
            'filename': filename,
            'authors': authors,
        }
        code = self.assemblyproxy.change_attachment_version(rs, data)
        rs.notify_return_code(code, success=n_("Attachment changed."))
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("attachment_ack_delete")
    def delete_attachment_version(self, rs: RequestState, assembly_id: int,
                                  attachment_id: int, version_nr: int,
                                  attachment_ack_delete: bool) -> Response:
        """Delete a version of an attachment."""
        if not attachment_ack_delete:
            rs.append_validation_error(
                ("attachment_ack_delete", ValueError(n_("Must be checked."))))
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/list_attachments")

        if not self.assemblyproxy.is_attachment_version_deletable(rs, attachment_id):
            rs.notify("error", n_("Attachment version can not be deleted."))
            return self.redirect(rs, "assembly/list_attachments")

        # This should not happen. Instead, the last attachment_version_delete button
        # should link directly to delete_attachment
        if rs.ambience["attachment"]['num_versions'] <= 1:
            rs.notify("error", n_("Cannot remove the last remaining"
                                  " version of an attachment."))
            return self.redirect(rs, "assembly/list_attachments")

        versions = self.assemblyproxy.get_attachment_versions(rs, attachment_id)
        if version_nr not in versions:
            rs.notify("error", n_("This version does not exist."))
            return self.redirect(rs, "assembly/list_attachments")
        if versions[version_nr]['dtime']:
            rs.notify("error", n_("This version has already been deleted."))
            return self.redirect(rs, "assembly/list_attachments")

        code = self.assemblyproxy.remove_attachment_version(
            rs, attachment_id, version_nr)
        rs.notify_return_code(code, error=n_("Unknown version."))
        return self.redirect(rs, "assembly/list_attachments")
