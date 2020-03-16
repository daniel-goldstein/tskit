#
# IT License
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
Test cases for combinatorial algorithms.
"""
import itertools
import unittest

import tskit
import tskit.combinatorics as comb
from tskit.combinatorics import RankTree


def all_labelled_trees(n):
    """
    Generate all unordered, leaf-labelled trees with n leaves.
    """
    for tree in all_unlabelled_trees(n):
        yield from all_labellings(tree)


def all_unlabelled_trees(n):
    """
    Generate all unlabelled trees of n leaves.

    Let S(n) be the set of all unlabelled trees of n leaves.

    A tree with n leaves can be obtained by joining m trees whose number
    of leaves sum to n. This means that we can enumerate all n-leaf trees
    by computing first all partitions* of n, and then for each
    partition p, compute the cross product of all k-leaf trees for k
    in p. For example, for n = 5 and p = [2, 3], we can see that
    S(2) x S(3) produces valid trees in S(5).

    A caveat arises, however, when dealing with partitions with repeated
    numbers of leaves. The use of ascending compositions for integer
    partitions gives a canonical ordering to the children of a given node
    (children are ordered by number of leaves, ascending),
    but symmetrical partitions could result in the generation of extra trees.

    To remove these redunant trees we reduce the set of trees assigned to
    each partition, so that if a subtree has the same number of leaves as
    its left sibling, then it must have a rank higher or equal to that of
    its left sibling.

    In the case of binary trees, this simplifies down to:
    Let P be a size-2 partition of n. If p_0 < p_1, then the trees generated by
    P are equivalent to S(p_0) x S(p_1). If p_0 == p_1 == p, then the trees
    generated are equivalent to all (s_i, s_j) where s_i is the i'th tree
    in S(p) and s_j is the j'th tree in S(p) and [i, j] is a 2-element
    combination with replacement of integers in [0, |S(p)|), i.e. i <= j.

    This generalizes to the algorithm of
        1. Group each subsequence of equal elements in a partition P of n.
        2. For a group G whose elements equal k, compute all
            combinations with replacement of |G| elements from S(k)
        3. Take the cartesian product of all groups

    Note: By grouping the partition of n into symmetrical groups, we eliminate
    symmetry between groups, allowing us to take the cartesian product of
    groups. This is a pattern that emerges again in labelling.

    *This excludes the partition [n], since trees with unary nodes are
     inumerable.
    """
    if n == 1:
        yield RankTree()
    else:
        for part in comb.partition(n):
            for subtree_pairing in all_subtree_pairings(comb.group_partition(part)):
                yield RankTree(children=subtree_pairing)


def all_subtree_pairings(grouped_part):
    if len(grouped_part) == 0:
        yield []
    else:
        g = grouped_part[0]
        k = g[0]
        all_k_leaf_trees = all_unlabelled_trees(k)
        num_k_leaf_trees = len(g)
        g_trees = itertools.combinations_with_replacement(
            all_k_leaf_trees, num_k_leaf_trees
        )
        for first_trees in g_trees:
            for rest in all_subtree_pairings(grouped_part[1:]):
                yield list(first_trees) + rest


def all_labellings(tree, labels=None):
    """
    Given a tree, generate all the unique labellings of that tree.
    We cannot have two distinct labellings where, under some number
    of mirroring of subtrees, the two trees become identical.

    To formulate this more easily, we assume that the given tree is in
    its canonical orientation. Let L(T) be the set of all unique
    labellings of an unlabelled tree, T.

    Let T be a tree in S(n), where the distribution of leaves across
    the subtrees of T is given by the partition P of n.
    Here, we face a similar problem of symmetry as in the unlabelled
    case. In this case the problem arises when T has identical subtrees,
    as switching those two trees would not violate the canonical
    orientation of the tree but would result in two different
    labelings.

    To remove this redundancy, we enforce that if two subtrees are
    equivalent, the left tree must have the minimum label out of
    all labels across the two subtrees. This canonical labelling removes
    any redundant trees and allows us the following enumeration
    algorithm.

    1. Group the subtrees of T into groups of *identical* trees. Note
        this means the trees must have the same shape, not only the
        same number of leaves.
    2. Let x = |G| and t be in S(k) for all t in G (all trees in G have
        the same number of leaves).
    3. For every combination of x * k labels from the available labels,
        for every assignment of those labels to the trees in G, and then
        for every unique labelling of the trees in G, produce
        the labelling of G crossed with every labelling of the rest of the
        groups with the rest of the labels.

        Regarding how to produce all the labelings of a single group G:
        Let t be the first tree in G. Since all trees in G are identical,
        by the canonical labelling we assign t the minimum label.
        Then, for every combination of k - 1 elements from the remaining
        x * k - 1 labels given to G, we give t that combination.
        Then, we cross all labellings of t with all the labellings
        of the rest of the trees in G labelled with the remaining
        (x - 1) * k labels.
    """
    if labels is None:
        labels = list(range(tree.num_leaves))

    if tree.is_leaf():
        assert len(labels) == 1
        yield RankTree(label=labels[0])
    else:
        groups = tree.group_children_by_shape()
        for labeled_children in label_all_groups(groups, labels):
            yield RankTree(children=labeled_children)


def label_all_groups(groups, labels):
    if len(groups) == 0:
        yield []
    else:
        g, rest = groups[0], groups[1:]
        x = len(g)
        k = g[0].num_leaves
        for g_labels in itertools.combinations(labels, x * k):
            rest_labels = comb.set_minus(labels, g_labels)
            for labeled_g in label_tree_group(g, g_labels):
                for labeled_rest in label_all_groups(rest, rest_labels):
                    yield labeled_g + labeled_rest


def label_tree_group(trees, labels):
    if len(trees) == 0:
        assert len(labels) == 0
        yield []
    else:
        first, rest = trees[0], trees[1:]
        k = first.num_leaves
        min_label = labels[0]
        for first_other_labels in itertools.combinations(labels[1:], k - 1):
            first_labels = [min_label] + list(first_other_labels)
            rest_labels = comb.set_minus(labels, first_labels)
            for labeled_first in all_labellings(first, first_labels):
                for labeled_rest in label_tree_group(rest, rest_labels):
                    yield [labeled_first] + labeled_rest


class TestCombination(unittest.TestCase):
    def test_combination_with_replacement_rank_unrank(self):
        for n in range(9):
            for k in range(n):
                nums = list(range(n))
                combs = itertools.combinations_with_replacement(nums, k)
                for exp_rank, c in enumerate(combs):
                    c = list(c)
                    actual_rank = comb.Combination.with_replacement_rank(c, n)
                    self.assertEqual(actual_rank, exp_rank)
                    unranked = comb.Combination.with_replacement_unrank(exp_rank, n, k)
                    self.assertEqual(unranked, c)

    def test_combination_rank_unrank(self):
        for n in range(11):
            for k in range(n):
                nums = list(range(n))
                for rank, c in enumerate(itertools.combinations(nums, k)):
                    c = list(c)
                    self.assertEqual(comb.Combination.rank(c, nums), rank)
                    self.assertEqual(comb.Combination.unrank(rank, nums, k), c)


class TestPartition(unittest.TestCase):
    def test_partition_doesnt_include_length_one(self):
        self.assertEqual(list(comb.partition(1)), [])
        self.assertEqual(list(comb.partition(2)), [[1, 1]])
        self.assertEqual(
            list(comb.partition(4)), [[1, 1, 1, 1], [1, 1, 2], [1, 3], [2, 2]]
        )

    def test_group_partition(self):
        self.assertEqual(comb.group_partition([1]), [[1]])
        self.assertEqual(comb.group_partition([1, 2]), [[1], [2]])
        self.assertEqual(comb.group_partition([1, 1, 1]), [[1, 1, 1]])
        self.assertEqual(comb.group_partition([1, 1, 2, 3, 3]), [[1, 1], [2], [3, 3]])


class TestRankTree(unittest.TestCase):
    def test_num_shapes(self):
        for i in range(11):
            self.assertEqual(len(list(all_unlabelled_trees(i))), comb.num_shapes(i))

    def test_num_labellings(self):
        for n in range(2, 8):
            for tree in all_unlabelled_trees(n):
                tree = tree.label_unrank(0)
                tree2 = tree.to_tsk_tree()
                n_labellings = sum(1 for _ in all_labellings(tree))
                self.assertEqual(
                    n_labellings, RankTree.from_tsk_tree(tree2).num_labellings()
                )

    def test_num_labelled_trees(self):
        # Number of leaf-labelled trees with n leaves on OEIS
        n_trees = [0, 1, 1, 4, 26, 236, 2752, 39208]
        for i, expected in zip(range(len(n_trees)), n_trees):
            actual = sum(1 for _ in all_labelled_trees(i))
            self.assertEqual(actual, expected)

    def test_all_labelled_trees_3(self):
        expected = ["(0,1,2)", "(0,(1,2))", "(1,(0,2))", "(2,(0,1))"]
        actual = [t.newick() for t in all_labelled_trees(3)]
        self.assertEqual(expected, actual)

    def test_all_labelled_trees_4(self):
        expected = [
            # 1 + 1 + 1 + 1 (partition of num leaves)
            "(0,1,2,3)",
            # 1 + 1 + 2
            "(0,1,(2,3))",
            "(0,2,(1,3))",
            "(0,3,(1,2))",
            "(1,2,(0,3))",
            "(1,3,(0,2))",
            "(2,3,(0,1))",
            # 1 + 3
            # partition of 3 = 1 + 1 + 1
            "(0,(1,2,3))",
            "(1,(0,2,3))",
            "(2,(0,1,3))",
            "(3,(0,1,2))",
            # partition of 3 = 1 + 2
            "(0,(1,(2,3)))",
            "(0,(2,(1,3)))",
            "(0,(3,(1,2)))",
            "(1,(0,(2,3)))",
            "(1,(2,(0,3)))",
            "(1,(3,(0,2)))",
            "(2,(0,(1,3)))",
            "(2,(1,(0,3)))",
            "(2,(3,(0,1)))",
            "(3,(0,(1,2)))",
            "(3,(1,(0,2)))",
            "(3,(2,(0,1)))",
            # 2 + 2
            "((0,1),(2,3))",
            "((0,2),(1,3))",
            "((0,3),(1,2))",
        ]
        actual = [t.newick() for t in all_labelled_trees(4)]
        self.assertEqual(expected, actual)

    def test_unrank(self):
        for n in range(6):
            for shape_rank, t in enumerate(all_unlabelled_trees(n)):
                for label_rank, labelled_tree in enumerate(all_labellings(t)):
                    unranked = RankTree.unrank((shape_rank, label_rank), n)
                    self.assertTrue(labelled_tree.equal(unranked))

        # The number of labelled trees gets very big quickly
        for n in range(6, 10):
            for shape_rank in range(comb.num_shapes(n)):
                rank = (shape_rank, 0)
                unranked = RankTree.unrank(rank, n)
                self.assertTrue(rank, unranked.rank())

                rank = (shape_rank, comb.num_labellings(shape_rank, n) - 1)
                unranked = RankTree.unrank(rank, n)
                self.assertTrue(rank, unranked.rank())

    def test_shape_rank(self):
        for n in range(10):
            for rank, tree in enumerate(all_unlabelled_trees(n)):
                self.assertEqual(tree.shape_rank(), rank)

    def test_shape_unrank(self):
        for n in range(6):
            for rank, tree in enumerate(all_unlabelled_trees(n)):
                t = RankTree.shape_unrank(rank, n)
                self.assertTrue(tree.shape_equal(t))

        for n in range(2, 9):
            for shape_rank, tree in enumerate(all_unlabelled_trees(n)):
                tsk_tree = comb.shape_unrank(shape_rank, n)
                self.assertEqual(shape_rank, tree.shape_rank())
                self.assertEqual(comb.shape_rank(tsk_tree), tree.shape_rank())

    def test_label_rank(self):
        for n in range(7):
            for tree in all_unlabelled_trees(n):
                for rank, labelled_tree in enumerate(all_labellings(tree)):
                    self.assertEqual(labelled_tree.label_rank(), rank)

    def test_label_unrank(self):
        for n in range(7):
            for shape_rank, tree in enumerate(all_unlabelled_trees(n)):
                for label_rank, labelled_tree in enumerate(all_labellings(tree)):
                    rank = (shape_rank, label_rank)
                    unranked = tree.label_unrank(label_rank)
                    self.assertEqual(labelled_tree.rank(), rank)
                    self.assertEqual(unranked.rank(), rank)

    def test_unrank_rank_round_trip(self):
        for n in range(6):  # Can do more but gets slow pretty quickly after 6
            for shape_rank in range(comb.num_shapes(n)):
                tree = RankTree.shape_unrank(shape_rank, n)
                tree = tree.label_unrank(0)
                self.assertEqual(tree.shape_rank(), shape_rank)
                for label_rank in range(tree.num_labellings()):
                    tree = tree.label_unrank(label_rank)
                    self.assertEqual(tree.label_rank(), label_rank)
                    tsk_tree = comb.label_unrank(tree.to_tsk_tree(), label_rank)
                    self.assertEqual(comb.label_rank(tsk_tree), label_rank)

    def test_is_canonical(self):
        for n in range(7):
            for tree in all_labelled_trees(n):
                self.assertTrue(tree.is_canonical())

        shape_not_canonical = RankTree(
            children=[
                RankTree(label=0),
                RankTree(
                    children=[
                        RankTree(children=[RankTree(label=1), RankTree(label=2)]),
                        RankTree(label=3),
                    ]
                ),
            ]
        )
        self.assertFalse(shape_not_canonical.is_canonical())

        labels_not_canonical = RankTree(
            children=[
                RankTree(label=0),
                RankTree(
                    children=[
                        RankTree(children=[RankTree(label=2), RankTree(label=3)]),
                        RankTree(children=[RankTree(label=1), RankTree(label=4)]),
                    ]
                ),
            ]
        )
        self.assertFalse(labels_not_canonical.is_canonical())

    def test_unranking_is_canonical(self):
        for n in range(7):
            for shape_rank in range(comb.num_shapes(n)):
                for label_rank in range(comb.num_labellings(shape_rank, n)):
                    t = RankTree.shape_unrank(shape_rank, n)
                    self.assertTrue(t.is_canonical())
                    t = t.label_unrank(label_rank)
                    self.assertTrue(t.is_canonical())
                    t = tskit.Tree.unrank((shape_rank, label_rank), n)
                    self.assertTrue(RankTree.from_tsk_tree(t).is_canonical())

    def test_to_from_tsk_tree(self):
        for n in range(5):
            for tree in all_labelled_trees(n):
                self.assertTrue(tree.is_canonical())
                tsk_tree = tree.to_tsk_tree()
                reconstructed = RankTree.from_tsk_tree(tsk_tree)
                self.assertTrue(tree.is_canonical())
                self.assertTrue(tree.equal(reconstructed))

    def test_rank_errors_multiple_roots(self):
        tables = tskit.TableCollection(sequence_length=1.0)

        # Nodes
        sv = [True, True]
        tv = [0.0, 0.0]

        for is_sample, t in zip(sv, tv):
            flags = tskit.NODE_IS_SAMPLE if is_sample else 0
            tables.nodes.add_row(flags=flags, time=t)

        ts = tables.tree_sequence()
        with self.assertRaises(ValueError):
            ts.first().rank()

    def test_big_trees(self):
        n = 14
        shape = 22
        labelling = 0
        tree = RankTree.unrank((shape, labelling), n)
        tsk_tree = tskit.Tree.unrank((shape, labelling), n)
        self.assertEqual(tree.rank(), tsk_tree.rank())

        n = 10
        shape = 95
        labelling = comb.num_labellings(shape, n) // 2
        tree = RankTree.unrank((shape, labelling), n)
        tsk_tree = tskit.Tree.unrank((shape, labelling), n)
        self.assertEqual(tree.rank(), tsk_tree.rank())

    def test_symmetrical_trees(self):
        for n in range(2, 18, 2):
            last_rank = comb.num_shapes(n) - 1
            t = RankTree.shape_unrank(last_rank, n)
            self.assertTrue(t.is_symmetrical())

    def test_equal(self):
        self.assertTrue(RankTree().equal(RankTree()))
        self.assertTrue(RankTree().shape_equal(RankTree()))

        self.assertTrue(RankTree(label=0).equal(RankTree(label=0)))
        self.assertFalse(RankTree(label=0).equal(RankTree(label=1)))
        self.assertTrue(RankTree(label=0).shape_equal(RankTree(label=1)))

        tree1 = RankTree(children=[RankTree(label=0), RankTree(label=1)])
        self.assertTrue(tree1.equal(tree1))
        self.assertFalse(tree1.equal(RankTree()))
        self.assertFalse(tree1.shape_equal(RankTree()))

        tree2 = RankTree(children=[RankTree(label=2), RankTree(label=1)])
        self.assertFalse(tree1.equal(tree2))
        self.assertTrue(tree1.shape_equal(tree2))

    def test_is_symmetrical(self):
        self.assertTrue(RankTree().is_symmetrical())
        three_leaf_asym = RankTree(
            children=[RankTree(), RankTree(children=[RankTree(), RankTree()])]
        )
        self.assertFalse(three_leaf_asym.is_symmetrical())
        six_leaf_sym = RankTree(children=[three_leaf_asym, three_leaf_asym])
        self.assertTrue(six_leaf_sym.is_symmetrical())
