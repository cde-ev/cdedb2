#!/usr/bin/env python3

"""Sample data used for dev instances."""

import dataclasses
from typing import Optional


@dataclasses.dataclass
class MockHeldMessage:
    request_id: int
    sender: str
    subject: str
    reason: Optional[str]
    msg: str


# Sample messages for the case that no mailman instance is available.
HELD_MESSAGE_SAMPLE = [
    MockHeldMessage(
        request_id=1, sender='kassenwart@example.cde',
        subject='Finanzbericht', reason='Nicht-Abonnent',
        msg="""
Received: from mail-il1-f180.google.com (mail-il1-f180.google.com [209.85.166.180])
	by mail.cde-ev.de (Postfix) with ESMTP id D03062000E7
	for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 18:36:08 +0100 (CET)
Received: by mail-il1-f180.google.com with SMTP id x15so20028263ilq.1
        for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 09:36:08 -0800 (PST)
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=gmail.com; s=20161025;
        h=mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=AnaGVaqslVzu6nvKOibF2ATCvUzNwKkuDlRHNe3Q0V20xHvsfnyEb9V+lvFf4mXhWY
         Cerg11qBWhpdKsk6rWlKBl5IPHY0wIRAM8N1h3vtKMfHuxyJ4U6k7LGEmlKXSuDl+QQk
         DAgL1ZpTtTjToEiP7QmOAQSOcG5jryV7KhbBrQSujHYv6s62MnNHYQXFnfkKBWgVCekf
         yFJ7oASV73GXZatnmDAAMhSRZBe39UjljlOCb4//S8G/XuSnponPrtdCzc4d67FTB4YL
         KyNwRpRF1/jMmKLkjXKKfgMj42EpIOwl7kA1uiyRA88HER3b56+1049Gi1kLybTkl9i1
         WFnA==
X-Google-DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=1e100.net; s=20161025;
        h=x-gm-message-state:mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=SEKJe6BemekvQQ+NEIBJIvSvG2GlNUn123x98BYNqnBUlkVqxpQzIo5W1+44NHB6Yk
         3FThiCdw3I9rT0FQUwrLYjZ1ZIBXCy7bWWmXvBONUAgIC196dVlCtsarDY/M7OJWmGqj
         H3KG6BVCq+Dmz9rhEM77Zd4nu+KaoPwKrUnVfJzmN1kgignUdUZ1oJsoir/s9snipX2h
         b94wF9FAmym3wQ3Z1wkLCsdlEyWy3H5GBnZMZmRJfgDc2dZi5lAE0puMhTyS1qw34P2J
         9MrSaVrFpXb8P7v25nw881EvfG7vZJCEHj45tH6I3sTsRJV3ymHtxfEUXIiNgfgUopOQ
         8U2w==
X-Gm-Message-State: AOAM530lMaqnS52U4kQrOddMRG5Ad7SPgbJZSkMrqj7MiwK/RaJX8nCA
	hn8iNHWPIJUlEHWiUmlwSxnN3wiIfzNwo2Ypr9c3QTbh
X-Google-Smtp-Source: ABdhPJyjYmKYwkmrNjBO0lVYclFiACiQIwht7Fr8W3PGSof4Slav7pBgn4SnnOS97LLxbFcPV7dmsQHM4oBwwcdDHUg=
X-Received: by 2002:a92:8404:: with SMTP id l4mr42107425ild.49.1608053767397;
 Tue, 15 Dec 2020 09:36:07 -0800 (PST)
MIME-Version: 1.0
From: Lokalgruppenleitung Bonn CdE <lokalleiter.cde.bonn@gmail.com>
Date: Tue, 15 Dec 2020 18:35:56 +0100
Message-ID: <CAJBhFmopLy3XW=fZ-=jBzEhwfKhUZ9cPEThauX+JV+kWt_E_SA@mail.gmail.com>
Subject: Test
To: mailman-migration@testmail.cde-ev.de
Content-Type: multipart/alternative; boundary="00000000000095e6f305b6843107"
X-MailFrom: lokalleiter.cde.bonn@gmail.com
X-Mailman-Rule-Hits: nonmember-moderation
X-Mailman-Rule-Misses: dmarc-mitigation; no-senders; approved; emergency; loop; banned-address; member-moderation
Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK
X-Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK

--00000000000095e6f305b6843107
Content-Type: text/plain; charset="UTF-8"

Test-Mail

--00000000000095e6f305b6843107
Content-Type: text/html; charset="UTF-8"

<div dir="ltr">Test-Mail</div>

--00000000000095e6f305b6843107--
""".strip()),
    MockHeldMessage(
        request_id=2, sender='illuminati@example.cde',
        subject='Verschwurbelung', reason='Zu riesig',
        msg="""
Received: from mail-il1-f180.google.com (mail-il1-f180.google.com [209.85.166.180])
	by mail.cde-ev.de (Postfix) with ESMTP id D03062000E7
	for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 18:36:08 +0100 (CET)
Received: by mail-il1-f180.google.com with SMTP id x15so20028263ilq.1
        for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 09:36:08 -0800 (PST)
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=gmail.com; s=20161025;
        h=mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=AnaGVaqslVzu6nvKOibF2ATCvUzNwKkuDlRHNe3Q0V20xHvsfnyEb9V+lvFf4mXhWY
         Cerg11qBWhpdKsk6rWlKBl5IPHY0wIRAM8N1h3vtKMfHuxyJ4U6k7LGEmlKXSuDl+QQk
         DAgL1ZpTtTjToEiP7QmOAQSOcG5jryV7KhbBrQSujHYv6s62MnNHYQXFnfkKBWgVCekf
         yFJ7oASV73GXZatnmDAAMhSRZBe39UjljlOCb4//S8G/XuSnponPrtdCzc4d67FTB4YL
         KyNwRpRF1/jMmKLkjXKKfgMj42EpIOwl7kA1uiyRA88HER3b56+1049Gi1kLybTkl9i1
         WFnA==
X-Google-DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=1e100.net; s=20161025;
        h=x-gm-message-state:mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=SEKJe6BemekvQQ+NEIBJIvSvG2GlNUn123x98BYNqnBUlkVqxpQzIo5W1+44NHB6Yk
         3FThiCdw3I9rT0FQUwrLYjZ1ZIBXCy7bWWmXvBONUAgIC196dVlCtsarDY/M7OJWmGqj
         H3KG6BVCq+Dmz9rhEM77Zd4nu+KaoPwKrUnVfJzmN1kgignUdUZ1oJsoir/s9snipX2h
         b94wF9FAmym3wQ3Z1wkLCsdlEyWy3H5GBnZMZmRJfgDc2dZi5lAE0puMhTyS1qw34P2J
         9MrSaVrFpXb8P7v25nw881EvfG7vZJCEHj45tH6I3sTsRJV3ymHtxfEUXIiNgfgUopOQ
         8U2w==
X-Gm-Message-State: AOAM530lMaqnS52U4kQrOddMRG5Ad7SPgbJZSkMrqj7MiwK/RaJX8nCA
	hn8iNHWPIJUlEHWiUmlwSxnN3wiIfzNwo2Ypr9c3QTbh
X-Google-Smtp-Source: ABdhPJyjYmKYwkmrNjBO0lVYclFiACiQIwht7Fr8W3PGSof4Slav7pBgn4SnnOS97LLxbFcPV7dmsQHM4oBwwcdDHUg=
X-Received: by 2002:a92:8404:: with SMTP id l4mr42107425ild.49.1608053767397;
 Tue, 15 Dec 2020 09:36:07 -0800 (PST)
MIME-Version: 1.0
From: Lokalgruppenleitung Bonn CdE <lokalleiter.cde.bonn@gmail.com>
Date: Tue, 15 Dec 2020 18:35:56 +0100
Message-ID: <CAJBhFmopLy3XW=fZ-=jBzEhwfKhUZ9cPEThauX+JV+kWt_E_SA@mail.gmail.com>
Subject: Test
To: mailman-migration@testmail.cde-ev.de
Content-Type: multipart/alternative; boundary="00000000000095e6f305b6843107"
X-MailFrom: lokalleiter.cde.bonn@gmail.com
X-Mailman-Rule-Hits: nonmember-moderation
X-Mailman-Rule-Misses: dmarc-mitigation; no-senders; approved; emergency; loop; banned-address; member-moderation
Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK
X-Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK

--00000000000095e6f305b6843107
Content-Type: text/plain; charset="UTF-8"

Test-Mail

--00000000000095e6f305b6843107
Content-Type: text/html; charset="UTF-8"

<div dir="ltr">Test-Mail</div>

--00000000000095e6f305b6843107--
""".strip()),
    MockHeldMessage(
        request_id=3,
        sender='nigerian_prince@example.cde',
        subject='unerwartetes Erbe',
        reason='Spam',
        msg="""
Received: from mail-il1-f180.google.com (mail-il1-f180.google.com [209.85.166.180])
	by mail.cde-ev.de (Postfix) with ESMTP id D03062000E7
	for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 18:36:08 +0100 (CET)
Received: by mail-il1-f180.google.com with SMTP id x15so20028263ilq.1
        for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 09:36:08 -0800 (PST)
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=gmail.com; s=20161025;
        h=mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=AnaGVaqslVzu6nvKOibF2ATCvUzNwKkuDlRHNe3Q0V20xHvsfnyEb9V+lvFf4mXhWY
         Cerg11qBWhpdKsk6rWlKBl5IPHY0wIRAM8N1h3vtKMfHuxyJ4U6k7LGEmlKXSuDl+QQk
         DAgL1ZpTtTjToEiP7QmOAQSOcG5jryV7KhbBrQSujHYv6s62MnNHYQXFnfkKBWgVCekf
         yFJ7oASV73GXZatnmDAAMhSRZBe39UjljlOCb4//S8G/XuSnponPrtdCzc4d67FTB4YL
         KyNwRpRF1/jMmKLkjXKKfgMj42EpIOwl7kA1uiyRA88HER3b56+1049Gi1kLybTkl9i1
         WFnA==
X-Google-DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=1e100.net; s=20161025;
        h=x-gm-message-state:mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=SEKJe6BemekvQQ+NEIBJIvSvG2GlNUn123x98BYNqnBUlkVqxpQzIo5W1+44NHB6Yk
         3FThiCdw3I9rT0FQUwrLYjZ1ZIBXCy7bWWmXvBONUAgIC196dVlCtsarDY/M7OJWmGqj
         H3KG6BVCq+Dmz9rhEM77Zd4nu+KaoPwKrUnVfJzmN1kgignUdUZ1oJsoir/s9snipX2h
         b94wF9FAmym3wQ3Z1wkLCsdlEyWy3H5GBnZMZmRJfgDc2dZi5lAE0puMhTyS1qw34P2J
         9MrSaVrFpXb8P7v25nw881EvfG7vZJCEHj45tH6I3sTsRJV3ymHtxfEUXIiNgfgUopOQ
         8U2w==
X-Gm-Message-State: AOAM530lMaqnS52U4kQrOddMRG5Ad7SPgbJZSkMrqj7MiwK/RaJX8nCA
	hn8iNHWPIJUlEHWiUmlwSxnN3wiIfzNwo2Ypr9c3QTbh
X-Google-Smtp-Source: ABdhPJyjYmKYwkmrNjBO0lVYclFiACiQIwht7Fr8W3PGSof4Slav7pBgn4SnnOS97LLxbFcPV7dmsQHM4oBwwcdDHUg=
X-Received: by 2002:a92:8404:: with SMTP id l4mr42107425ild.49.1608053767397;
 Tue, 15 Dec 2020 09:36:07 -0800 (PST)
MIME-Version: 1.0
From: Lokalgruppenleitung Bonn CdE <lokalleiter.cde.bonn@gmail.com>
Date: Tue, 15 Dec 2020 18:35:56 +0100
Message-ID: <CAJBhFmopLy3XW=fZ-=jBzEhwfKhUZ9cPEThauX+JV+kWt_E_SA@mail.gmail.com>
Subject: Test
To: mailman-migration@testmail.cde-ev.de
Content-Type: multipart/alternative; boundary="00000000000095e6f305b6843107"
X-MailFrom: lokalleiter.cde.bonn@gmail.com
X-Mailman-Rule-Hits: nonmember-moderation
X-Mailman-Rule-Misses: dmarc-mitigation; no-senders; approved; emergency; loop; banned-address; member-moderation
Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK
X-Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK

--00000000000095e6f305b6843107
Content-Type: text/plain; charset="UTF-8"

Test-Mail

--00000000000095e6f305b6843107
Content-Type: text/html; charset="UTF-8"

<div dir="ltr">Test-Mail</div>

--00000000000095e6f305b6843107--
""".strip()),
]
