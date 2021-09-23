Markdown
========

Crashkurs
---------

+-------------------------------------------------------+-------------------------------------------------+
| Eingabe                                               | Ausgabe                                         |
+=======================================================+=================================================+
| ``*kursiver Text* mit einfachen Sternen``             | *kursiver Text* mit einfachen Sternen           |
+-------------------------------------------------------+-------------------------------------------------+
| ``**fetter Text** mit doppelten Sternen``             | **fetter Text** mit doppelten Sternen           |
+-------------------------------------------------------+-------------------------------------------------+
| ``Links mit spitzen Klammern. <http://www.cde-ev.de>``| Links mit spitzen Klammern http://www.cde-ev.de |
+-------------------------------------------------------+-------------------------------------------------+
| ``[Link mit eigenem Text](http://www.cde-ev.de)``     | `Link mit eigenem Text <http://www.cde-ev.de>`_ |
+-------------------------------------------------------+-------------------------------------------------+

Absätze durch eine Leerzeile trennen::

    Ein Absatz.

    Nächster Absatz.

ergibt

Ein Absatz.

Nächster Absatz.

----

Aufzählungen mittels Strichen am Anfang::

    - ein Punkt
    - noch ein Punkt

ergibt

- ein Punkt
- noch ein Punkt

----

Nummerierte Listen mit Zahl plus Punkt am Anfang::

    1. erster Punkt,
    2. zweiter Punkt.

ergibt

1. erster Punkt,
2. zweiter Punkt.

----

Überschriften mit ``#``, Unterüberschriften mit ``##``::

    # Überschrift
    ## Unterüberschrift
    und etwas Text.

ergibt

Überschrift
-----------
Unterüberschrift
^^^^^^^^^^^^^^^^
und etwas Text.

----

Eine längere Einführung gibt es im `Markdown Guide
<https://www.markdownguide.org/basic-syntax/>`_.

Spezifikation
-------------

Dieser Abschnitt enthält Informationen zu den technischen Details der Syntax, die für das Schreiben einfacher
Markdown-Texte nicht benötigt werden.

Die CdE-Datenbank verwendet das ``python3-markdown``-Modul in Version 3.3.4, um Markdown zu HTML zu parsen. Das so
entstandene HTML wird anschließend bis auf eine Liste erlaubter Tags und Attribute escapet. Es ist also auch möglich,
direkt HTML zu verwenden. Folgende `Extensions <https://www.markdownguide.org/basic-syntax/>`_ werden verwendet:

- ``extra``
- ``sane_lists``
- ``smarty`` (mit deutschen Anführungszeichen)
- ``toc``

Folgende HTML-Tags sind erlaubt: ``a``, ``abbr``, ``acronym``, ``b``, ``blockquote``, ``br``, ``code``, ``colgroup``,
``col``, ``del``, ``details``, ``div``, ``dl``, ``dt``, ``dd``, ``em``, ``i``, ``li``, ``h1``, ``h2``, ``h3``, ``h4``,
``h5``, ``h6``, ``hr``, ``ol``, ``p``, ``pre``, ``s``, ``small``, ``span``, ``strong``, ``sub``, ``summary``. ``sup``,
``table``, ``tbody``, ``td``, ``tr``, ``th``, ``thead``, ``tt``, ``u``, ``ul``

Folgende Attribute dürfen verwendet werden::

    '*': ['class', 'id'],
    'a': ['href', 'title'],
    'abbr': ['title'],
    'acronym': ['title'],
    'col': ['width'],
    'details': ['open'],
    'thead': ['valign'],
    'tbody': ['valign'],
    'table': ['border'],
    'th': ['colspan', 'rowspan'],
    'td': ['colspan', 'rowspan'],
    'div': ['id'],
    'h4': ['id'],
    'h5': ['id'],
    'h6': ['id']
