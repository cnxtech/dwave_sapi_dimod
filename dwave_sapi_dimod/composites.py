import dimod

from dwave_sapi2.remote import RemoteConnection
from dwave_sapi2.local import local_connection
from dwave_sapi2.core import solve_ising, solve_qubo
from dwave_sapi2.util import get_hardware_adjacency
from dwave_sapi2.embedding import find_embedding, embed_problem, unembed_answer

from dwave_sapi_dimod import _PY2

if _PY2:
    iteritems = lambda d: d.iteritems()
else:
    iteritems = lambda d: d.items()


class EmbeddingComposite(dimod.TemplateComposite):
    """Composite for applying embedding a problem for a SAPISampler.

    Args:
        sampler: A dwave_sapi_dimod sampler object.

    Attributes:
        children (list): [`sampler`] where `sampler` is the input sampler.
        structure: None, converts the structuted sampler to an unstructured
            one.

    Examples:
        Composing a sampler:

        >>> sampler = sapi.EmbeddingComposite(sapi.SAPILocalSampler(solver_name))

        The composed sampler can now be used as a dimod sampler

        >>> response = sampler.sample_ising({}, {})

    """
    def __init__(self, sampler):
        # puts sampler into self.children
        dimod.TemplateComposite.__init__(self, sampler)

        self._child = sampler  # faster access than self.children[0]

        # structure becomes None
        self.structure = None

    @dimod.decorators.ising(1, 2)
    @dimod.decorators.ising_index_labels(1, 2)
    def sample_ising(self, h, J, **sapi_kwargs):
        """Embeds the given problem using sapi's find_embedding then invokes
        the given sampler to solve it.

        Args:
            h (dict/list): The linear terms in the Ising problem. If a
                dict, should be of the form {v: bias, ...} where v is
                a variable in the Ising problem, and bias is the linear
                bias associated with v. If a list, should be of the form
                [bias, ...] where the indices of the biases are the
                variables in the Ising problem.
            J (dict): A dictionary of the quadratic terms in the Ising
                problem. Should be of the form {(u, v): bias} where u,
                v are variables in the Ising problem and bias is the
                quadratic bias associated with u, v.
            Additional keyword parameters are the same as for
            SAPI's solve_ising function, see QUBIST documentation.

        Returns:
            :class:`dimod.SpinResponse`: The unembedded samples.

        Examples:
            >>> sampler = sapi.EmbeddingComposite(sapi.SAPILocalSampler('c4-sw_optimize'))
            >>> response = sampler.sample_ising({}, {(0, 1): 1, (0, 2): 1, (1, 2): 1})

        """

        sampler = self._child

        # sapi expects a list, ising_index_labels converted the keys of
        # h to be indices 0, n-1
        h_list = [0.] * len(h)
        for v, bias in iteritems(h):
            h_list[v] = bias

        # find an embedding
        (nodes, edges) = sampler.structure
        S = set(J)
        S.update({(v, v) for v in h})
        embeddings = find_embedding(S, edges)

        if J and not embeddings:
            raise Exception('No embedding found')

        # now it is possible that h_list might include nodes not in embedding, so let's
        # handle that case here
        if len(h_list) > len(embeddings):
            emb_qubits = set().union(*embeddings)
            while len(h_list) > len(embeddings):
                for v in solver.properties['qubits']:
                    if v not in emb_qubits:
                        embeddings.append([v])
                        emb_qubits.add(v)
                        break

        # embed the problem
        h0, j0, jc, new_emb = embed_problem(h_list, J, embeddings, edges)

        emb_j = j0.copy()
        emb_j.update(jc)

        if 'chains' in sampler.solver.properties['parameters'] and 'chains' not in sapi_kwargs:
            sapi_kwargs['chains'] = new_emb

        emb_response = sampler.sample_ising(h0, emb_j, **sapi_kwargs)

        answers = [[sample[i] for i in range(len(sample))] for sample in emb_response]

        # parse the answers
        solutions = unembed_answer(answers, new_emb, 'minimize_energy', h_list, J)

        samples = ({v: sample[v] for v in h} for sample in solutions)

        sample_data = (data for __, data in emb_response.samples(data=True))

        response = dimod.SpinResponse()
        response.add_samples_from(samples, sample_data=sample_data, h=h, J=J)

        return response
