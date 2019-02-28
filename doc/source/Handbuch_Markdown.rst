Crashkurs Markdown
==================

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

Eine längere Einführung gibt es im `Markdwon Guide
<https://www.markdownguide.org/basic-syntax/>`_.
