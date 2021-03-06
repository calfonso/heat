# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from heat.common import exception
from heat.engine import resource

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

#
# We are ignoring Policies and Groups as keystone does not support them.
#
# For now support users and accesskeys.
#


class User(resource.Resource):
    properties_schema = {'Path': {'Type': 'String'},
                         'Groups': {'Type': 'List'},
                         'LoginProfile': {'Type': 'Map',
                                          'Schema': {
                                              'Password': {'Type': 'String'}
                                          }},
                         'Policies': {'Type': 'List'}}

    def __init__(self, name, json_snippet, stack):
        super(User, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        passwd = ''
        if self.properties['LoginProfile'] and \
                'Password' in self.properties['LoginProfile']:
                passwd = self.properties['LoginProfile']['Password']

        uid = self.keystone().create_stack_user(self.physical_resource_name(),
                                                passwd)
        self.resource_id_set(uid)

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        if self.resource_id is None:
            logger.error("Cannot delete User resource before user created!")
            return
        self.keystone().delete_stack_user(self.resource_id)

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())

    def FnGetAtt(self, key):
        #TODO Implement Arn attribute
        raise exception.InvalidTemplateAttribute(
            resource=self.physical_resource_name(), key=key)


class AccessKey(resource.Resource):
    properties_schema = {'Serial': {'Type': 'Integer',
                                    'Implemented': False},
                         'UserName': {'Type': 'String',
                                      'Required': True},
                         'Status': {'Type': 'String',
                                    'Implemented': False,
                                    'AllowedValues': ['Active', 'Inactive']}}

    def __init__(self, name, json_snippet, stack):
        super(AccessKey, self).__init__(name, json_snippet, stack)
        self._secret = None

    def _get_userid(self):
        """
        Helper function to derive the keystone userid, which is stored in the
        resource_id of the User associated with this key.  We want to avoid
        looking the name up via listing keystone users, as this requires admin
        rights in keystone, so FnGetAtt which calls _secret_accesskey won't
        work for normal non-admin users
        """
        # Lookup User resource by intrinsic reference (which is what is passed
        # into the UserName parameter.  Would be cleaner to just make the User
        # resource return resource_id for FnGetRefId but the AWS definition of
        # user does say it returns a user name not ID
        for r in self.stack.resources:
            refid = self.stack.resources[r].FnGetRefId()
            if refid == self.properties['UserName']:
                return self.stack.resources[r].resource_id

    def handle_create(self):
        user_id = self._get_userid()
        if user_id is None:
            raise exception.NotFound('could not find user %s' %
                                     self.properties['UserName'])

        kp = self.keystone().get_ec2_keypair(user_id)
        if not kp:
            raise exception.Error("Error creating ec2 keypair for user %s" %
                                  user_id)
        else:
            self.resource_id_set(kp.access)
            self._secret = kp.secret

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        self.resource_id_set(None)
        self._secret = None
        user_id = self._get_userid()
        if user_id and self.resource_id:
            self.keystone().delete_ec2_keypair(user_id, self.resource_id)

    def _secret_accesskey(self):
        '''
        Return the user's access key, fetching it from keystone if necessary
        '''
        user_id = self._get_userid()
        if self._secret is None:
            if not self.resource_id:
                logger.warn('could not get secret for %s Error:%s' %
                            (self.properties['UserName'],
                            "resource_id not yet set"))
            else:
                try:
                    kp = self.keystone().get_ec2_keypair(user_id)
                except Exception as ex:
                    logger.warn('could not get secret for %s Error:%s' %
                                (self.properties['UserName'],
                                 str(ex)))
                else:
                    if kp.access == self.resource_id:
                        self._secret = kp.secret
                    else:
                        msg = ("Unexpected ec2 keypair, for %s access %s" %
                               (user_id, kp.access))
                        logger.error(msg)

        return self._secret or '000-000-000'

    def FnGetAtt(self, key):
        res = None
        log_res = None
        if key == 'UserName':
            res = self.properties['UserName']
            log_res = res
        elif key == 'SecretAccessKey':
            res = self._secret_accesskey()
            log_res = "<SANITIZED>"
        else:
            raise exception.InvalidTemplateAttribute(
                resource=self.physical_resource_name(), key=key)

        logger.info('%s.GetAtt(%s) == %s' % (self.physical_resource_name(),
                                             key, log_res))
        return unicode(res)


def resource_mapping():
    return {
        'AWS::IAM::User': User,
        'AWS::IAM::AccessKey': AccessKey,
    }
