Internationalization
====================

We use GNU gettext in combination with the python babel library for
internationalization.

* Translatable strings have to be marked. In python you can do this in two ways:

    * using ``n_()``. This only marks the string for extraction into
      internationalization files, but does not translate it.
    * using ``rs.gettext()``. This marks the string, but also replaces it with
      the translation.

* You can also translate strings in templates, by wrapping them in either of the following.
  Both of these ways replace the marked string with the appropriate translation.

    * the ``rs.gettext()`` function or its common alias ``_()`` where appropriate.
    * the ``{% trans %}`` / ``{% endtrans %}`` environment.

* Marked strings are extracted via the ``make i18n-refresh`` command.
* The extracted strings need to be translated in the ``*.po`` files in the
  ``i18n`` directory for each language.
* Ultimately pybabel needs to be compiled(``make i18n-compile``) and the apache
  restarted. This can both be done via one command: ``make reload``.

Be aware that messages that need to be translated, but do not appear explicitly
in the code, are listed in ``i18n_additional.py``. This applies especially
human-readable descriptions of enum members.
