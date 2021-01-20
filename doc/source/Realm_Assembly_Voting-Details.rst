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

Internally, we handle them equal, so we have only one complex facility of
determining results and not two which are used in parallel.

Additionally, we allow for both voting types to include an optional rejection
option into the vote. So, we gain in total four different combinations of vote
settings.


Preferential Votes
------------------

In a preferential vote, one can sort the candidates in a hierarchical
way, according to your preference. Therefore, the the relational operators
``>`` and ``=`` are be used to rank all candidates relatively to each other.

A sample preferential vote string might look as follows::

  Charly=Daniel>Anton>Berta=Nina>Jannis

In our example, there exists four different level of preferences:
Charly and Daniel got equally the highest preference, while Anton gets lower
preference. Berta and Nina get both even lower preference than Anton, but are
still higher preferenced than Jannis, who gots the lowest preference in this
vote.

Note that the steps between every level of preferences are *equidistant*; there
is no way you can rank Berta and Nina lower to Anton than you can rank Charly
and Daniel higher to Anton; both distances are the same.

If you want to *abstain* from a vote, meaning none of the candidates were more
preferred by you than an other, you put them all equal to each other::

  Anton=Berta=Charly=Daniel=Jannis=Nina

Optional Rejection
^^^^^^^^^^^^^^^^^^

As mentioned above, we allow to include an optional rejection limit
into a voting. This works through introducing an additional candidate named
``_bar_`` and let the voter include this into his preferential vote.

A sample preferential vote string with rejection option might look as follows::

  Charly=Daniel>Anton>_bar_>Berta=Nina>Jannis

In this modified example, Charly, Daniel and Anton got higher preference than
the rejection option, while Berta, Nina and Jannis got lower preference than the
rejection option. We call this "*winning* or *loosing* against the bar"
respectively.

You could also rank candidates equal to the ``_bar_``. In this case, you express
that this candidates neither get higher nor lower preference than your the
rejection limit, but you are indifferent about them.

So, also the following is a legal preferential vote string with rejection option::

  Charly=Daniel>_bar_=Anton>Berta=Nina>Jannis

Now Charly and Daniel are still winning against the bar, while Berta, Nina and
Jannis are loosing against the bar. Anton is treated in a neutral way, he is
neither accepted nor rejected.

Of course, you can also rank all candidates higher, equal or lower to the
``_bar_``, meaning you accept, abstain or reject all candidates.

Counting votes
^^^^^^^^^^^^^^

During voting, every attendee of an assembly may vote in each of its ballots and
the vote will be stored in the database. After the voting period ends, we need
to determine a result by taking all given votes into account.

To solve this task, we use the `Schulze Method`_ internally. We therefore get
an overall preference string reflecting the result of the voting. Note that we
do not have equidistant steps between each candidate level anymore. Instead,
the method gives us two numbers of votes for each level, representing how many
voters ranked this level higher than the next lower level (Pro Votes) and how
many voters ranked this level lower than the next lower level (Contra Votes).

Presentation of result
^^^^^^^^^^^^^^^^^^^^^^

After the voting has been tallied, we create a result file in which we store
the important information of the vote, including the candidates, each given vote
and the combined preference string, which can be used to verified the result,
see :doc:`Realm_Assembly_Voting-Procedere` for more information.

We show the combined preference, together with the Pro and Contra counts for
each preference level, to the user.


Classical Vote
--------------


.. _Schulze Method: https://en.wikipedia.org/w/index.php?title=Schulze_method&oldid=904460701
