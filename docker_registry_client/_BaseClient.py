import logging
from requests import get, put, delete
from requests.exceptions import HTTPError
import json

# urllib3 throws some ssl warnings with older versions of python
#   they're probably ok for the registry client to ignore
import warnings
warnings.filterwarnings("ignore")


class CommonBaseClient(object):
    def __init__(self, host):
        self.host = host

    def _http_response(self, url, method, data=None, **kwargs):
        """url -> full target url
           method -> method from requests
           data -> request body
           kwargs -> url formatting args
        """
        header = {'content-type': 'application/json'}
        if data:
            data = json.dumps(data)
        response = method(self.host + url.format(**kwargs),
                          data=data, headers=header)
        if not response.ok:
            logging.error("Error response: %r", response.text)
            response.raise_for_status()

        return response

    def _http_call(self, url, method, data=None, **kwargs):
        """url -> full target url
           method -> method from requests
           data -> request body
           kwargs -> url formatting args
        """
        response = self._http_response(url, method, data=data, **kwargs)
        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError:
            logging.error("Unable to decode json for response %r, url %s",
                          response.text, url.format(**kwargs))
            raise


class BaseClientV1(CommonBaseClient):
    IMAGE_LAYER = '/v1/images/{image_id}/layer'
    IMAGE_JSON = '/v1/images/{image_id}/json'
    IMAGE_ANCESTRY = '/v1/images/{image_id}/ancestry'
    REPO = '/v1/repositories/{namespace}/{repository}'
    TAGS = REPO + '/tags'

    @property
    def version(self):
        return 1

    def search(self, q=''):
        """GET /v1/search"""
        if q:
            q = '?q=' + q
        return self._http_call('/v1/search' + q, get)

    def check_status(self):
        """GET /v1/_ping"""
        return self._http_call('/v1/_ping', get)

    def get_images_layer(self, image_id):
        """GET /v1/images/{image_id}/layer"""
        return self._http_call(self.IMAGE_LAYER, get, image_id=image_id)

    def put_images_layer(self, image_id, data):
        """PUT /v1/images/(image_id)/layer"""
        return self._http_call(self.IMAGE_LAYER, put,
                               image_id=image_id, data=data)

    def put_image_layer(self, image_id, data):
        """PUT /v1/images/(image_id)/json"""
        return self._http_call(self.IMAGE_JSON, put,
                               data=data, image_id=image_id)

    def get_image_layer(self, image_id):
        """GET /v1/images/(image_id)/json"""
        return self._http_call(self.IMAGE_JSON, get, image_id=image_id)

    def get_image_ancestry(self, image_id):
        """GET /v1/images/(image_id)/ancestry"""
        return self._http_call(self.IMAGE_ANCESTRY, get, image_id=image_id)

    def get_repository_tags(self, namespace, repository):
        """GET /v1/repositories/(namespace)/(repository)/tags"""
        return self._http_call(self.TAGS, get,
                               namespace=namespace, repository=repository)

    def get_image_id(self, namespace, respository, tag):
        """GET /v1/repositories/(namespace)/(repository)/tags/(tag*)"""
        return self._http_call(self.TAGS + '/' + tag, get,
                               namespace=namespace, repository=respository)

    def get_tag_json(self, namespace, repository, tag):
        """GET /v1/repositories(namespace)/(repository)tags(tag*)/json"""
        return self._http_call(self.TAGS + '/' + tag + '/json', get,
                               namespace=namespace, repository=repository)

    def delete_repository_tag(self, namespace, repository, tag):
        """DELETE /v1/repositories/(namespace)/(repository)/tags/(tag*)"""
        return self._http_call(self.TAGS + '/' + tag, delete,
                               namespace=namespace, repository=repository)

    def set_tag(self, namespace, repository, tag, image_id):
        """PUT /v1/repositories/(namespace)/(repository)/tags/(tag*)"""
        return self._http_call(self.TAGS + '/' + tag, put, data=image_id,
                               namespace=namespace, repository=repository)

    def delete_repository(self, namespace, repository):
        """DELETE /v1/repositories/(namespace)/(repository)/"""
        return self._http_call(self.REPO, delete,
                               namespace=namespace, repository=repository)


class BaseClientV2(CommonBaseClient):
    LIST_TAGS = '/v2/{name}/tags/list'
    MANIFEST = '/v2/{name}/manifests/{reference}'
    BLOB = '/v2/{name}/blobs/{digest}'

    def __init__(self, *args, **kwargs):
        super(BaseClientV2, self).__init__(*args, **kwargs)
        self._manifest_digests = {}

    @property
    def version(self):
        return 2

    def check_status(self):
        return self._http_call('/v2/', get)

    def catalog(self):
        return self._http_call('/v2/_catalog', get)

    def get_repository_tags(self, name):
        return self._http_call(self.LIST_TAGS, get, name=name)

    def get_manifest_and_digest(self, name, reference):
        response = self._http_response(self.MANIFEST, get,
                                       name=name, reference=reference)
        self._cache_manifest_digest(name, reference, response=response)
        return (response.json(), self._manifest_digests[name, reference])

    def delete_manifest(self, name, digest):
        return self._http_call(self.MANIFEST, delete,
                               name=name, reference=digest)

    def delete_blob(self, name, digest):
        return self._http_call(self.BLOB, delete,
                               name=name, digest=digest)

    def _cache_manifest_digest(self, name, reference, response=None):
        if not response:
            # TODO: create our own digest
            raise NotImplementedError()

        untrusted_digest = response.headers.get('Docker-Content-Digest')
        self._manifest_digests[(name, reference)] = untrusted_digest


def BaseClient(host):
    # Try V2 first
    v2_client = BaseClientV2(host)
    try:
        v2_client.check_status()
    except HTTPError as e:
        if e.response.status_code == 404:
            return BaseClientV1(host)

        raise
    else:
        return v2_client