Voting Details
==============

This page aims to explain in an ordered fashion the subtle details of our voting
data model.


Type of Votes
-------------

We currently support two different types of voting procedures which we expose to
the user:

* Preferential Votes
* Classical Votes

Additionally, we allow for both voting types to include an optional rejection
option into the vote. So, we gain in total four different combinations of vote
settings.

Internally, we model classical votes as preferential ones, so we have only one
complex facility of determining the result of a ballot and not two used in parallel.


Preferential Votes
------------------

In a preferential vote, one can sort the candidates in a hierarchical
way, according to their preference. For this, the relational operators
``>`` and ``=`` are used to rank all candidates relatively to each other.

A sample preferential vote string might look as follows::

  Charly=Daniel>Anton>Berta=Nina>Janis

In our example, there exists four different levels of preferences:
Charly and Daniel got equally the highest preference, while Anton gets lower
preference. Berta and Nina get both even lower preference than Anton, but are
still higher preferred than Janis, who got the lowest preference in this vote.

Note that the preferential vote is a purely ordinal ranking and does not allow
to specify a cardinality between the candidates. In other words, you may only
specify in which relative order you prefer each level of candidates, but you
can not describe which specific preference about a level is most important to
you.

If you want to *abstain* from a vote, meaning none of the candidates were more
preferred by you than any other, you put them all equal to each other::

  Anton=Berta=Charly=Daniel=Janis=Nina

Optional Rejection
^^^^^^^^^^^^^^^^^^

As mentioned above, we allow to include an optional rejection limit
into a voting. This works through introducing an additional candidate named
``_bar_`` and let the voter include this into his preferential vote.

A sample preferential vote string with rejection option might look as follows::

  Charly=Daniel>Anton>_bar_>Berta=Nina>Janis

In this modified example, Charly, Daniel and Anton got higher preference than
the rejection option, while Berta, Nina and Janis got lower preference than the
rejection option. We call this "*winning* or *loosing* against the bar"
respectively.

You could also rank candidates equal to the ``_bar_``. In this case, your vote
will be treated as abstention with regard to those candidates.

So, also the following is a legal preferential vote string with rejection option::

  Charly=Daniel>Anton=_bar_>Berta=Nina>Janis

Now Charly and Daniel are still winning against the bar, while Berta, Nina and
Janis are loosing against the bar. The voter abstained with regard to Anton.

Of course, you can also rank all candidates higher, equal or lower to the
``_bar_``, meaning you accept, abstain or reject all candidates.

Counting votes
^^^^^^^^^^^^^^

During voting, every attendee of an assembly may vote in each of its ballots and
the vote will be stored in the database. After the voting period ends, we need
to determine a result per ballot taking all given votes into account.

To solve this task, we use the `Schulze Method`_ internally. We therefore get
an overall preference string reflecting the result of the voting.

Additionally, we provide some extra information per level of preference:
We count how many votes ranked a level A higher than the next lower one
(calling this Pro Votes for level A) and, in contrast, how many votes ranked
level A lower than the next lower level (calling this Contra Votes for level A).

Presentation of result
^^^^^^^^^^^^^^^^^^^^^^

After the ballot has been tallied, we create a result file in which we store
the important information of the vote, including the candidates, each given vote
and the combined preference string, which can be used to verify the result(
see :doc:`Realm_Assembly_Voting-Procedere` for more information).

We show the combined preference and the Pro and Contra counts for each level of
preference to the user.


Classical Vote
--------------

In classical votes, the voter gets a specified amount of *individual votes*,
which can be distributed over all candidates. Only one vote per candidate is
allowed, unused votes are lost.

Internal, we map classical votes into preferential votes. Since we only allow a
maximum of one vote per candidate and give no possibility of ranking between
candidates, we got at most two preference levels of candidates:
Those which were chosen, and those which were not chosen.

Lets take the following example ballot with **3 individual votes** and the
following candidates:

* |uncheck| Anton
* |uncheck| Berta
* |uncheck| Charly
* |uncheck| Daniel

Voting like

* |check| Anton
* |check| Berta
* |uncheck| Charly
* |check| Daniel

will be mapped to the preference string::

  Anton=Berta=Daniel>Charly

We may not assign all individual votes, so also the following would be a legal vote

* |uncheck| Anton
* |check| Berta
* |uncheck| Charly
* |uncheck| Daniel

which will be mapped to the string::

  Berta>Anton=Charly=Daniel

To abstain, we simply do not assign any individual vote at all, so this would be

* |uncheck| Anton
* |uncheck| Berta
* |uncheck| Charly
* |uncheck| Daniel

and will be mapped to the string::

  Anton=Berta=Charly=Daniel

.. warning::
  Since we are allowed to assign any number of individual votes from *0 (abstaining)*
  to *the total number of candidates*, we can not distinguish between
  *abstaining* on the one hand and *voting for all candidates* on the other hand.

  To circumvent this problem, we introduce an **implicit _bar_** option into each
  vote. Implicit means here, the voter can not chose the ``_bar_`` option, but the
  vote will be treated as if it was available and simply not chosen.

With employing this trick, we can distinguish between those two voting
scenarios, since voting for all candidates

* |check| Anton
* |check| Berta
* |check| Charly
* |check| Daniel

will result in the preference string::

  Anton=Berta=Charly=Daniel>_bar_

while abstaining

* |uncheck| Anton
* |uncheck| Berta
* |uncheck| Charly
* |uncheck| Daniel

will result in the different preference string::

  Anton=Berta=Charly=Daniel=_bar_

Optional rejection
^^^^^^^^^^^^^^^^^^

As mentioned above, we allow also a rejection options in classical votes. This
is also denoted as ``_bar_`` but has a slightly different semantically meaning:
It behaves as option to **reject all candidates**.

I the a voter choose the ``_bar_`` option, all other individual votes are lost.
So, the following is a legal vote

* |uncheck| Anton
* |uncheck| Berta
* |uncheck| Charly
* |uncheck| Daniel
* |check| _bar_

translated into the preference string::

  _bar_>Anton=Berta=Charly=Daniel

but a voting like

* |uncheck| Anton
* |uncheck| Berta
* |check| Charly
* |uncheck| Daniel
* |check| _bar_

is prohibited: You can not choose one candidate and simultaneously reject all.

Abstaining behaves similar to abstaining without explicit ``_bar_`` option.

Counting votes
^^^^^^^^^^^^^^

During voting, every attendee of an assembly may vote in each of its ballots and
the vote will be stored in the database. After the voting period ends, we need
to determine a result per ballot taking all given votes into account.

Since we mapped all classical votes to preferential vote strings internally,
we can use exactly the same mechanism to obtain the result of a ballot (the
already mentioned `Schulze Method`_).

We can also obtain the exact number of votes for each candidate: The numbers of
*Pro votes* for each level of preference are directly reported by the evaluating
method, and every candidate got votes equal to the number of *Pro votes* of his
own level. The number of *Contra votes* has no meaning in this scenario.

Presentation of result
^^^^^^^^^^^^^^^^^^^^^^

After the ballot has been tallied, we create a result file in which we store
the important information of the vote, including the candidates, each given vote
and the combined preference string, which can be used to verify the result(
see :doc:`Realm_Assembly_Voting-Procedere` for more information).

We show the combined preference and the Pro counts for each level of preference to
the user.

.. _Schulze Method: https://en.wikipedia.org/w/index.php?title=Schulze_method&oldid=904460701


.. from https://stackoverflow.com/a/58639467
.. |check| raw:: html

    <input checked=""  type="checkbox">

.. |uncheck| raw:: html

    <input type="checkbox">
