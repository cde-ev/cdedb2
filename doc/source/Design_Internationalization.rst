Internationalization (i18n)
===========================

.. seealso::
    The description of our :doc:`Development Internationalization Workflow <Development_Workflows_Internationalization>`.

Homonyms
--------

Some English words have semantically different meanings. To distinguish them in
our translations (where desired), we use the following format::

    Homonymic-phrase_[[semantic meaning]]

Consider the englisch word **vote** as an example:

1. abstimmen: ``vote_[[to vote in a ballot]]``
2. Stimme: ``vote_[[on a voting paper]]``

Gendering
---------

Die CdE-Datenbank nutzt im Deutschen gendergerechte Sprache anstelle des generischen Maskulinums.
Es folgen ein paar kurze Richtlinien, damit die Nutzung von gendergerechter Sprache möglichst einheitlich geschieht.
Präferiere die Richtlinien von oben nach unten.

* Grundsätzlich:
   * Nutze Satzgefüge, die ohne Gendering auskommen (bspw. "Du hast diese Mailingliste abonniert." statt "Du bis Abonnent dieser Mailingliste").
   * Nutze genderneutrale Ausdrücke, sofern sie existieren (bspw. "Admin" statt "Administrator", "Teilnahmebeitrag" statt "Teilnehmerbeitrag").
* Im Singular:
   * Nutze Paarformen, die mit einem Doppelpunkt getrennt sind (bspw. "Moderator:in").
* Im Plural:
   * Nutze substantivierte Adjektive und Partizipien (bspw. "Teilnehmende", "Kursleitende").
   * Sonst nutze analog zum Singular mit Doppelpunkt getrennte Paarformen (bspw. "Veranstaltungshelfer:innen")
