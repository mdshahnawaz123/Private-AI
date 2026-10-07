import unittest
from types import SimpleNamespace
from unittest.mock import patch
import auth


class CurrentUserAuthorization(unittest.TestCase):
    request=SimpleNamespace(headers={'authorization':'Bearer token'},query_params={})
    def test_disabled_and_deleted_user_tokens_are_rejected(self):
        for current in (None,{'id':9,'username':'former','role':'admin','is_active':False}):
            with patch('auth.decode_token',return_value={'sub':'9','role':'admin'}),patch('db.get_user',return_value=current):
                self.assertIsNone(auth.user_from_request(self.request))

    def test_current_role_overrides_stale_admin_token(self):
        with patch('auth.decode_token',return_value={'sub':'9','role':'admin'}),patch('db.get_user',return_value={'id':9,'username':'reviewer','role':'user','is_active':True}):
            self.assertEqual(auth.user_from_request(self.request)['role'],'user')

    def test_password_rotation_revokes_previous_token(self):
        with patch('auth.decode_token',return_value={'sub':'9','ver':0}),patch('db.get_user',return_value={'id':9,'username':'reviewer','role':'user','is_active':True,'auth_version':1}):
            self.assertIsNone(auth.user_from_request(self.request))

if __name__=='__main__':unittest.main()
