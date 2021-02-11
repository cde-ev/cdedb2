Template-Renderer
=================

Die Mitnahmeversion enthält standardmäßig den
`Template Renderer <https://tracker.cde-ev.de/gitea/orgas/cde_template_renderer_v3>`_
mit dem ihr verschiedenste Dokumente mittels LaTeX aus den
Veranstaltungsdaten erstellen könnt. Für die allgemeine Benutzung des
Template Renderers schaut bei obigem Link nach.

In der Mitnahmeversion findet ihr den Template Renderer im Verzeichnis
``/home/cdedb/cde_template_renderer_v3/``. Es gibt außerdem noch zwei kleine
Arbeitserleichterungen. Das Skript
``/home/cdedb/refresh_template_renderer_data.py`` erneuert den partiellen
Export mit dem der Template Renderer arbeitet mit frischen Daten aus der
lokalen DB der VM. Die fertigen PDF-Dateien könnt ihr dann unter
`https://localhost:20443/render/ <https://localhost:20443/render/>`_
abrufen; dabei müsst ihr möglicherweise ``localhost:20443`` entsprechend
der Konfiguration eurer VM anpassen.
