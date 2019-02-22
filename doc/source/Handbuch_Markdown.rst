Crashkurs reStructuredText
==========================

+-----------------------------------------------------+-------------------------------------------------+
| Eingabe                                             | Ausgabe                                         |
+=====================================================+=================================================+
| ``*kursiver Text* mit einfachen Sternen``           | *kursiver Text* mit einfachen Sternen           |
+-----------------------------------------------------+-------------------------------------------------+
| ``**fetter Text** mit doppelten Sternen``           | **fetter Text** mit doppelten Sternen           |
+-----------------------------------------------------+-------------------------------------------------+
| ``Links direkt im Text bspw. http://www.cde-ev.de`` |	Links direkt im Text bspw. http://www.cde-ev.de	|  
+-----------------------------------------------------+-------------------------------------------------+

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

Tabellen analog folgenden Beispiels::

    ======  ======  ========
       Eingang      Ausgang 
    --------------  -------- 
      A       B     A oder B 
    ======  ======  ======== 
    Falsch  Falsch  Falsch 
    Wahr    Falsch  Wahr 
    Falsch  Wahr    Wahr 
    Wahr    Wahr    Wahr 
    ======  ======  ========  

ergibt

======  ======  ========
   Eingang      Ausgang 
--------------  -------- 
  A       B     A oder B 
======  ======  ======== 
Falsch  Falsch  Falsch 
Wahr    Falsch  Wahr 
Falsch  Wahr    Wahr 
Wahr    Wahr    Wahr 
======  ======  ========  

----

Überschriften indem in der nächsten Zeile mit ``=`` oder ``-``
unterschrichen wird::

    Überschrift
    ===========
    Unterüberschrift
    ----------------
    und etwas Text.

ergibt

Überschrift
===========
Unterüberschrift
----------------
und etwas Text.

----

Eine längere Einführung gibt es im `reStructuredText Primer
<http://docutils.sourceforge.net/docs/user/rst/quickstart.html>`_.
