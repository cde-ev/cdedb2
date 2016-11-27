Workflows
=========

This page aims to provide descriptions on how to do things.

Internationalization
--------------------

We use GNU gettext in combination with the python babel library for
internationalization.

* First the translatable strings have to be marked. In python files this is
  done with ``_()`` which also works in the templates, there however also
  the ``{% trans %}`` / ``{% endtrans %}`` environment is available.

  FIXME maybe allow rs.gettext?

* Second they have to be extracted via ``make i18n-refresh``.

* Third the translations have to be added to the ``*.po`` files in the
  ``i18n`` directory.

* Fourth they can now be used via (FIXME insert correct calls)
