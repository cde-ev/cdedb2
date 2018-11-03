Workflows
=========

This page aims to provide descriptions on how to do things.

Internationalization
--------------------

We use GNU gettext in combination with the python babel library for
internationalization.

* Translatable strings have to be marked. In python you can do this in two ways:
	* using ``n_()``. This only marks the string for extraction into internationalization fi, but does not tranlate it.
	* using ``rs.gettext()``. This marks the string, but also replaces it with the translation.

* You can also translate strings in templates, by wrapping them in either of the following.
  Both these way replace the marked string with the appropriate translation.
	* the ``rs.gettext()`` function or it' common alias ``_()`` where appropriate.
	* the ``{% trans %}`` / ``{% endtrans %}`` environment.

* Marked strings are extracted via the ``make i18n-refresh`` command.

* The extracted strings need to be translated in the ``*.po`` files in the ``i18n``
  directory for each language.