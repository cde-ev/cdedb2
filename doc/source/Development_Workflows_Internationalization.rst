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

* Marked strings are extracted via the ``make i18n-extract`` command.
* The extracted strings are stored in the ``cdedb.po`` files in the ``i18n`` directory
  (one file per language) via the ``make i18n-update`` command.
  This also takes care of formatting the po-file. Run (just) this command if you want
  to update the formatting of the file.
* The ``make i18n-refresh`` command combines the two above and should be run, after new
  strings were added in the code.
* The strings in the ``cdedb.po`` file(s) then need to be translated.
* Ultimately pybabel needs to be compiled(``make i18n-compile``) and the apache
  restarted (for the changes to take effect in the browser).
  This can both be done via one command: ``make reload``.
* The ``make i18n-check`` command performs some basic checks on the po-files.
  For example it will tell you if a format specifier is missing in a translation.
  It will also tell you how many untranslated strings there are.
  For the german translation file, there should not be any untranslated strings
  (there exists a test in the test suite, that makes sure of this).
* You can find untranslated strings in the po-files by searching for ``""\n\n``
  (empty quotes followed by a blank line).

Be aware that messages that need to be translated, but do not appear explicitly
in the code, need to be added manually to the ``i18n_additional.py`` file, so that
they are then extracted. This applies especially to human-readable descriptions of
enum members.

Some english words have multiple (semantically different) meanings, which may
corresponde to different words in other languages. Our approach to handle such
homonyms is described in the Design section :doc:`Design_Internationalisation`.
