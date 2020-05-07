#
# MIT License
#
# Copyright (c) 2020 Tskit Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
Module for ranking and unranking trees. Trees are considered only
leaf-labelled and unordered, so order of children does not influence equality.
"""
import heapq
from functools import lru_cache

import tskit


def rank(tree):
    """
    The rank of a tree is composed of two parts:
    1. The shape rank - its rank in the enumeration of all unlabelled
        trees of n leaves.
    2. The label rank - its rank in the enumeration of all labelings
        of this tree.
    """
    return RankTree.from_tsk_tree(tree).rank()


def shape_rank(tree):
    return RankTree.from_tsk_tree(tree).shape_rank()


def label_rank(tree):
    return RankTree.from_tsk_tree(tree).label_rank()


def unrank(rank, num_leaves):
    """
    Reconstruct the tree of the given ``rank`` (see :func: `tskit.combinatorics.rank`)
    with ``num_leaves`` leaves. The labels and times of internal nodes are chosen
    arbitrarily, and the time of each leaf is 0.

    :param tuple(int) rank: The rank of the tree to generate.
    :param int num_leaves: The number of leaves of the tree to generate.
    :rtype: Tree
    """
    return RankTree.unrank(rank, num_leaves).to_tsk_tree()


def shape_unrank(shape_rank, num_leaves):
    """
    Reconstruct the tree of the given shape rank ``shape_rank``
    (see :func: `tskit.combinatorics.rank`) with ``num_leaves`` leaves.
    Leaves are labelled in increasing order from left to right.

    :param int shape_rank: The shape rank of the tree to generate.
    :param int num_leaves: The number of leaves of the tree to generate.
    :rtype: Tree
    """
    return RankTree.unrank((shape_rank, 0), num_leaves).to_tsk_tree()


def label_unrank(tree, label_rank):
    """
    Produce a tree identical in shape to ``tree`` with the labelling
    corresponding to the given label rank ``rank``
    (see :func: `tskit.combinatorics.rank`).

    :param Tree tree: The tree to relabel.
    :param int label_rank: The rank of the labelling of ``tree`` to use.
    :rtype: Tree
    """
    return RankTree.from_tsk_tree(tree).label_unrank(label_rank).to_tsk_tree()


class RankTree:
    """
    A tree class that maintains the topological ranks of each node in the tree.
    This structure can be used to efficiently compute the rank of a tree of
    n leaves and produce a tree given a rank.
    """

    def __init__(self, shape_rank=None, label_rank=None, children=None, label=None):
        self.children = children if children is not None else []
        if children is None:
            self.num_leaves = 1
            self.labels = [label]
        else:
            self.num_leaves = sum(c.num_leaves for c in children)
            self.labels = list(heapq.merge(*(c.labels for c in children)))

        if shape_rank is not None:
            self._shape_rank = shape_rank
        else:
            self._shape_rank = self.compute_shape_rank()
        self._label_rank = label_rank

    def compute_shape_rank(self):
        """
        Mirroring the way in which unlabelled trees are enumerated, we must
        first calculate the number of trees whose partitions of number of leaves
        rank lesser than this tree's partition.

        Once we reach the partition of leaves in this tree, we examine the
        groups of child subtrees assigned to subsequences of the partition.
        For each group of children with the same number of leaves, k, the trees
        in that group were selected according to a combination with replacement
        of those trees from S(k). By finding the rank of that combination,
        we find how many combinations preceded the current one in that group.
        That rank is then multiplied by the total number of arrangements that
        could be made in the following groups, added to the total rank,
        and then we recur on the rest of the group and groups.
        """
        part = self.leaf_partition()
        total = 0
        for prev_part in partition(self.num_leaves):
            if prev_part == part:
                break
            total += num_tree_pairings(prev_part)

        child_groups = self.group_children_by_num_leaves()
        next_child_idx = 0
        for g in child_groups:
            next_child_idx += len(g)
            k = g[0].num_leaves
            S_k = num_shapes(k)

            child_ranks = [c._shape_rank for c in g]
            g_rank = Combination.with_replacement_rank(child_ranks, S_k)

            # TODO precompute vector before loop
            rest_part = part[next_child_idx:]
            total_rest = num_tree_pairings(rest_part)

            total += g_rank * total_rest

        return total

    def add_label_ranks(self):
        """
        Again mirroring how we've labeled a particular tree, T, we can rank the
        labelling on T.

        We group the children into symmetric groups. In the context of labelling,
        symmetric groups contain child trees that are of the same shape. Each
        group contains a combination of labels selected from all the labels
        available to T.

        The different variables to consider are:
        1. How to assign a combination of labels to the first group.
        2. Given a combination of labels assigned to the group, how can we
            distribute those labels to each tree in the group.
        3. Given an assignment of the labels to each tree in the group, how many
            distinct ways could all the trees in the group be labelled.

        These steps for generating labelled trees break down the stages of
        ranking them.
        For each group G, we can find the rank of the combination of labels
        assigned to G. This rank times the number of ways the trees in G
        could be labelled, times the number of possible labellings of the
        rest of the trees, gives the number of labellings that precede those with
        the given combination of labels assigned to G. This process repeats and
        breaks down to give the rank of the assignment of labels to trees in G,
        and the label ranks of the trees themselves in G.
        """
        for c in self.children:
            c.add_label_ranks()

        all_labels = self.labels
        child_groups = self.group_children_by_shape()
        total = 0
        for i, g in enumerate(child_groups):
            rest_groups = child_groups[i + 1 :]
            g_labels = list(heapq.merge(*(t.labels for t in g)))
            num_rest_labellings = num_list_of_group_labellings(rest_groups)

            # Preceded by all of the ways to label all the groups
            # with a lower ranking combination given to g.
            comb_rank = Combination.rank(g_labels, all_labels)
            num_g_labellings = num_group_labellings(g)
            preceding_comb = comb_rank * num_g_labellings * num_rest_labellings

            # Preceded then by all the configurations of g ranking less than
            # the current one
            rank_from_g = group_rank(g) * num_rest_labellings

            total += preceding_comb + rank_from_g
            all_labels = set_minus(all_labels, g_labels)

        self._label_rank = total

    # TODO I think this would boost performance if it were a field and not
    # recomputed.
    def num_labellings(self):
        if self.is_leaf():
            return 1

        child_groups = self.group_children_by_shape()
        return num_list_of_group_labellings(child_groups)

    def rank(self):
        return self.shape_rank(), self.label_rank()

    def shape_rank(self):
        return self._shape_rank

    def label_rank(self):
        if self._label_rank is None:
            assert self._shape_rank is not None
            self.add_label_ranks()
        return self._label_rank

    @staticmethod
    def unrank(rank, num_leaves):
        shape_rank, label_rank = rank
        unlabelled = RankTree.shape_unrank(shape_rank, num_leaves)
        return unlabelled.label_unrank(label_rank)

    @staticmethod
    def shape_unrank(shape_rank, n):
        """
        Generate an unlabelled tree with n leaves with a shape corresponding to
        the `shape_rank`.
        """
        if n == 1:
            assert shape_rank == 0
            return RankTree(shape_rank=0)

        part, child_shape_ranks = children_shape_ranks(shape_rank, n)
        children = [
            RankTree.shape_unrank(rk, k) for rk, k in zip(child_shape_ranks, part)
        ]
        return RankTree(shape_rank=shape_rank, children=children)

    def label_unrank(self, label_rank, labels=None):
        """
        Generate a tree with the same shape, whose leaves are labelled
        from `labels` with the labelling corresponding to `label_rank`.
        """
        if labels is None:
            labels = list(range(self.num_leaves))

        if self.is_leaf():
            assert label_rank == 0
            assert len(labels) == 1
            return RankTree(label=labels[0], label_rank=label_rank)

        child_groups = self.group_children_by_shape()
        child_labels, child_label_ranks = children_label_ranks(
            child_groups, label_rank, labels
        )

        children = self.children
        labelled_children = [
            RankTree.label_unrank(c, c_rank, c_labels)
            for c, c_rank, c_labels in zip(children, child_label_ranks, child_labels)
        ]

        return RankTree(
            children=labelled_children,
            shape_rank=self._shape_rank,
            label_rank=label_rank,
        )

    @staticmethod
    def canonical_order(c):
        """
        Defines the canonical ordering of sibling subtrees.
        """
        return c.num_leaves, c._shape_rank, c.min_label()

    @staticmethod
    def from_tsk_tree_node(tree, u):
        if tree.is_leaf(u):
            return RankTree(label=u)

        children = list(
            sorted(
                (RankTree.from_tsk_tree_node(tree, c) for c in tree.children(u)),
                key=RankTree.canonical_order,
            )
        )
        return RankTree(children=children)

    @staticmethod
    def from_tsk_tree(tree):
        if len(tree.roots) != 1:
            raise ValueError("Can't rank trees with multiple roots")

        rank_tree = RankTree.from_tsk_tree_node(tree, tree.root)
        rank_tree.add_label_ranks()
        return rank_tree

    def to_tsk_tree(self):
        seq_length = 1
        tables = tskit.TableCollection(seq_length)

        def add_node(node):
            if node.is_leaf():
                assert node.label is not None
                return node.label

            child_ids = [add_node(child) for child in node.children]
            # Arbitrarily set parent time +1 from their oldest child
            max_child_time = max(tables.nodes.time[c] for c in child_ids)
            parent_id = tables.nodes.add_row(time=max_child_time + 1)
            for child_id in child_ids:
                tables.edges.add_row(0, seq_length, parent_id, child_id)

            return parent_id

        for _ in range(self.num_leaves):
            tables.nodes.add_row(flags=tskit.NODE_IS_SAMPLE, time=0)
        add_node(self)

        # Have to sort for now because the of the first way
        # in which we're traversing the edges
        tables.sort()
        return tables.tree_sequence().first()

    def newick(self):
        if self.is_leaf():
            return str(self.label) if self.labelled() else ""
        return "(" + ",".join(c.newick() for c in self.children) + ")"

    @property
    def label(self):
        return self.labels[0]

    def labelled(self):
        return all(l is not None for l in self.labels)

    def min_label(self):
        return self.labels[0]

    def is_leaf(self):
        return len(self.children) == 0

    def leaf_partition(self):
        return [c.num_leaves for c in self.children]

    def group_children_by_num_leaves(self):
        def same_num_leaves(c1, c2):
            return c1.num_leaves == c2.num_leaves

        return group_by(self.children, same_num_leaves)

    def group_children_by_shape(self):
        def same_shape(c1, c2):
            return c1.num_leaves == c2.num_leaves and c1._shape_rank == c2._shape_rank

        return group_by(self.children, same_shape)

    def equal(self, other):
        if self.is_leaf() and other.is_leaf():
            return self.label == other.label

        if len(self.children) != len(other.children):
            return False

        return all(c1.equal(c2) for c1, c2 in zip(self.children, other.children))

    def shape_equal(self, other):
        if self.is_leaf() and other.is_leaf():
            return True

        if len(self.children) != len(other.children):
            return False

        return all(c1.shape_equal(c2) for c1, c2 in zip(self.children, other.children))

    def is_canonical(self):
        if self.is_leaf():
            return True

        children = self.children
        for c1, c2 in zip(children, children[1:]):
            if RankTree.canonical_order(c1) > RankTree.canonical_order(c2):
                return False
        return all(c.is_canonical() for c in children)

    def is_symmetrical(self):
        if self.is_leaf():
            return True

        even_split_leaves = len(set(self.leaf_partition())) == 1
        all_same_rank = len({c.shape_rank() for c in self.children}) == 1

        return even_split_leaves and all_same_rank


# TODO This is called repeatedly in ranking and unranking and has a perfect
# subtructure for DP. It's only every called on n in [0, num_leaves]
# so we should compute a vector of those results up front instead of using
# repeated calls to this function.
# Put an lru_cache on for now as a quick replacement (cuts test time down by 80%)
@lru_cache()
def num_shapes(n):
    """
    The cardinality of the set of unlabelled binary trees with n leaves,
    under the conditions of tree isomorphism universal to this module.
    """
    if n <= 1:
        return n
    return sum(num_tree_pairings(part) for part in partition(n))


def num_tree_pairings(part):
    """
    The number of unique tree shapes that could be assembled from
    a given partition of leaves. If we group the elements of the partition
    by number of leaves, each group can be independently enumerated and the
    cardinalities of each group's pairings can be multiplied. Within a group,
    subsequent trees must have equivalent or greater rank, so the number of
    ways to select trees follows combinations with replacement from the set
    of all possible trees for that group.
    """
    total = 1
    for g in group_partition(part):
        k = g[0]
        total *= Combination.comb_with_replacement(num_shapes(k), len(g))
    return total


def num_labellings(shape_rk, n):
    return RankTree.shape_unrank(shape_rk, n).num_labellings()


def children_shape_ranks(rank, n):
    """
    Return the partition of leaves associated
    with the children of the tree of rank `rank`, and
    the ranks of each child tree.
    """
    assert n > 1, n
    assert 0 <= rank < num_shapes(n)

    num_prior_trees = 0
    part = None
    for prev_part in partition(n):
        num_trees_with_part = num_tree_pairings(prev_part)
        if num_prior_trees + num_trees_with_part > rank:
            part = prev_part
            break
        num_prior_trees += num_trees_with_part
    assert part is not None

    # Remaining is the rank given the current partition
    rank -= num_prior_trees

    grouped_part = group_partition(part)
    child_ranks = []
    next_child = 0
    for g in grouped_part:
        next_child += len(g)
        k = g[0]

        # TODO precompute vector up front
        rest_children = part[next_child:]
        rest_num_pairings = num_tree_pairings(rest_children)

        shapes_comb_rank = rank // rest_num_pairings
        g_shape_ranks = Combination.with_replacement_unrank(
            shapes_comb_rank, num_shapes(k), len(g)
        )
        child_ranks += g_shape_ranks
        rank %= rest_num_pairings

    return part, child_ranks


def children_label_ranks(child_groups, rank, labels):
    """
    Produces the subsets of labels assigned to each child
    and the associated label rank of each child.
    """
    child_labels = []
    child_label_ranks = []

    for i, g in enumerate(child_groups):
        k = g[0].num_leaves
        g_num_leaves = k * len(g)
        num_g_labellings = num_group_labellings(g)
        # TODO precompute vector of partial products outside of loop
        rest_groups = child_groups[i + 1 :]
        num_rest_labellings = num_list_of_group_labellings(rest_groups)

        num_labellings_per_label_comb = num_g_labellings * num_rest_labellings
        comb_rank = rank // num_labellings_per_label_comb
        rank_given_label_comb = rank % num_labellings_per_label_comb
        g_rank = rank_given_label_comb // num_rest_labellings

        g_labels = Combination.unrank(comb_rank, labels, g_num_leaves)

        g_child_labels, g_child_ranks = group_label_ranks(g_rank, g, g_labels)
        child_labels += g_child_labels
        child_label_ranks += g_child_ranks

        labels = set_minus(labels, g_labels)
        rank %= num_rest_labellings

    return child_labels, child_label_ranks


def group_rank(g):
    k = g[0].num_leaves
    n = len(g) * k
    # Num ways to label a single one of the trees
    # We can do this once because all the trees in the group
    # are of the same shape rank
    y = g[0].num_labellings()
    all_labels = list(heapq.merge(*(t.labels for t in g)))
    rank = 0
    for i, t in enumerate(g):
        u_labels = t.labels
        curr_trees = len(g) - i
        # Kind of cheating here leaving the selection of min labels implicit
        # because the rank of the comb without min labels is the same
        comb_rank = Combination.rank(u_labels, all_labels)

        # number of ways to distribute labels to rest leaves
        num_rest_combs = 1
        remaining_leaves = n - (i + 1) * k
        for j in range(curr_trees - 1):
            num_rest_combs *= Combination.comb(remaining_leaves - j * k - 1, k - 1)

        preceding_combs = comb_rank * num_rest_combs * (y ** curr_trees)
        curr_comb = t._label_rank * num_rest_combs * (y ** (curr_trees - 1))
        rank += preceding_combs + curr_comb
        all_labels = set_minus(all_labels, u_labels)
    return rank


# TODO This is only used in a few cases and mostly in a n^2 way. Would
# be easy and useful to do this DP and produce a list of partial products
def num_list_of_group_labellings(groups):
    """
    Given a set of labels and a list of groups, how many unique ways are there
    to assign subsets of labels to each group in the list and subsequently
    label all the trees in all the groups.
    """
    remaining_leaves = sum(len(g) * g[0].num_leaves for g in groups)
    total = 1
    for g in groups:
        k = g[0].num_leaves
        x = len(g)
        num_label_choices = Combination.comb(remaining_leaves, x * k)
        total *= num_label_choices * num_group_labellings(g)
        remaining_leaves -= x * k

    return total


def num_group_labellings(g):
    """
    Given a particular set of labels, how many unique ways are there
    to assign subsets of labels to each tree in the group and subsequently
    label those trees.
    """
    # Shortcut because all the trees are identical and can therefore
    # be labelled in the same ways
    num_tree_labelings = g[0].num_labellings() ** len(g)
    return num_assignments_in_group(g) * num_tree_labelings


def num_assignments_in_group(g):
    """
    Given this group of identical trees, how many unique ways
    are there to divide up a set of n labels?
    """
    if len(g) == 0:
        return 1

    k = g[0].num_leaves
    n = k * len(g)
    total = 1
    for n in range(k * len(g), 0, -k):
        # Choose k - 1 from n - 1 because the minimum label must be
        # assigned to the first tree for a canonical labelling.
        total *= Combination.comb(n - 1, k - 1)
    return total


def group_label_ranks(rank, child_group, labels):
    """
    Given a group of trees of the same shape, a label rank and list of labels,
    produce assignment of label subsets to each tree in the group and the
    label rank of each tree.
    """
    child_labels = []
    child_label_ranks = []

    for i, rank_tree in enumerate(child_group):
        k = rank_tree.num_leaves
        num_t_labellings = rank_tree.num_labellings()
        rest_trees = child_group[i + 1 :]
        num_rest_assignments = num_assignments_in_group(rest_trees)
        num_rest_labellings = num_rest_assignments * (
            num_t_labellings ** len(rest_trees)
        )
        num_labellings_per_label_comb = num_t_labellings * num_rest_labellings

        comb_rank = rank // num_labellings_per_label_comb
        rank_given_comb = rank % num_labellings_per_label_comb
        t_rank = rank_given_comb // num_rest_labellings
        rank %= num_rest_labellings

        min_label = labels[0]
        t_labels = [min_label] + Combination.unrank(comb_rank, labels[1:], k - 1)
        labels = set_minus(labels, t_labels)

        child_labels.append(t_labels)
        child_label_ranks.append(t_rank)

    return child_labels, child_label_ranks


class Combination:
    @staticmethod
    def comb(n, k):
        """
        The number of times you can select k items from
        n items without order and without replacement.

        FIXME: This function will be available in `math` in Python 3.8
        and should be replaced eventually.
        """
        k = min(k, n - k)
        res = 1
        for i in range(1, k + 1):
            res *= n - k + i
            res //= i

        return res

    @staticmethod
    def comb_with_replacement(n, k):
        """
        Also called multichoose, the number of times you can select
        k items from n items without order but *with* replacement.
        """
        return Combination.comb(n + k - 1, k)

    @staticmethod
    def rank(combination, elements):
        """
        Find the combination of k elements from the given set of elements
        with the given rank in a lexicographic ordering.
        """
        indices = [elements.index(x) for x in combination]
        return Combination.from_range_rank(indices, len(elements))

    @staticmethod
    def from_range_rank(combination, n):
        """
        Find the combination of k integers from [0, n)
        with the given rank in a lexicographic ordering.
        """
        k = len(combination)
        if k == 0 or k == n:
            return 0

        j = combination[0]
        combination = [x - 1 for x in combination]
        if j == 0:
            return Combination.from_range_rank(combination[1:], n - 1)

        first_rank = Combination.comb(n - 1, k - 1)
        rest_rank = Combination.from_range_rank(combination, n - 1)
        return first_rank + rest_rank

    @staticmethod
    def unrank(rank, elements, k):
        n = len(elements)
        if k == 0:
            return []

        n_rest_combs = Combination.comb(n - 1, k - 1)
        if rank < n_rest_combs:
            return elements[:1] + Combination.unrank(rank, elements[1:], k - 1)

        return Combination.unrank(rank - n_rest_combs, elements[1:], k)

    @staticmethod
    def with_replacement_rank(combination, n):
        """
        Find the rank of ``combination`` in the lexicographic ordering of
        combinations with replacement of integers from [0, n).
        """
        k = len(combination)
        if k == 0:
            return 0
        j = combination[0]
        if k == 1:
            return j

        if j == 0:
            return Combination.with_replacement_rank(combination[1:], n)

        rest = [x - j for x in combination[1:]]
        preceding = 0
        for i in range(j):
            preceding += Combination.comb_with_replacement(n - i, k - 1)
        return preceding + Combination.with_replacement_rank(rest, n - j)

    @staticmethod
    def with_replacement_unrank(rank, n, k):
        """
        Find the combination with replacement of k integers from [0, n)
        with the given rank in a lexicographic ordering.
        """
        if k == 0:
            return []

        i = 0
        preceding = Combination.comb_with_replacement(n, k - 1)
        while rank >= preceding:
            rank -= preceding
            i += 1
            preceding = Combination.comb_with_replacement(n - i, k - 1)

        rest = Combination.with_replacement_unrank(rank, n - i, k - 1)
        return [i] + [x + i for x in rest]


########################################################################
# Helpers
########################################################################


def set_minus(arr, subset):
    return [x for x in arr if x not in set(subset)]


# TODO I think we can use part-count form everywhere. Right now
# there's a janky work-around of grouping the partition when
# we needed in part-count form but it doesn't look like there's any
# place that can't just accept it from the start.
def partition(n):
    """
    Ascending integer partitions of n.
    """
    if n > 0:
        yield from rule_asc(n)


def rule_asc(n):
    a = [0 for _ in range(n + 1)]
    k = 1
    a[1] = n
    while k != 0:
        x = a[k - 1] + 1
        y = a[k] - 1
        k -= 1
        while x <= y:
            a[k] = x
            y -= x
            k += 1
        a[k] = x + y
        # TODO nicer way to avoid the partition [n]?
        if k == 0:
            return
        else:
            yield a[: k + 1]


def group_by(values, equal):
    groups = []
    curr_group = []
    for x in values:
        if len(curr_group) == 0 or equal(x, curr_group[0]):
            curr_group.append(x)
        else:
            groups.append(curr_group)
            curr_group = [x]

    if len(curr_group) != 0:
        groups.append(curr_group)
    return groups


def group_partition(part):
    return group_by(part, lambda x, y: x == y)
