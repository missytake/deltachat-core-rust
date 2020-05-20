from __future__ import print_function

import os.path
import shutil

import pytest
from filecmp import cmp

from deltachat import const


def wait_msgs_changed(account, chat_id, msg_id=None):
    account.log("waiting for chat_id={} msg_id={}".format(chat_id, msg_id))
    while 1:
        ev = account._evtracker.get_matching("DC_EVENT_MSGS_CHANGED")
        if ev.data1 != chat_id:
            account.log("waiting got mismatched DC_EVENT_MSGS_CHANGED")
            continue
        if msg_id is not None:
            assert ev.data2 == msg_id
        return ev.data2


class TestOnlineInCreation:
    def test_increation_not_blobdir(self, tmpdir, acfactory, lp):
        ac1, ac2 = acfactory.get_two_online_accounts()

        c2 = ac1.create_contact(email=ac2.get_config("addr"))
        chat = ac1.create_chat_by_contact(c2)

        lp.sec("Creating in-creation file outside of blobdir")
        assert tmpdir.strpath != ac1.get_blobdir()
        src = tmpdir.join('file.txt').ensure(file=1)
        with pytest.raises(Exception):
            chat.prepare_message_file(src.strpath)

    def test_no_increation_copies_to_blobdir(self, tmpdir, acfactory, lp):
        ac1, ac2 = acfactory.get_two_online_accounts()

        c2 = ac1.create_contact(email=ac2.get_config("addr"))
        chat = ac1.create_chat_by_contact(c2)

        lp.sec("Creating file outside of blobdir")
        assert tmpdir.strpath != ac1.get_blobdir()
        src = tmpdir.join('file.txt')
        src.write("hello there\n")
        chat.send_file(src.strpath)

        blob_src = os.path.join(ac1.get_blobdir(), 'file.txt')
        assert os.path.exists(blob_src), "file.txt not copied to blobdir"

    def test_forward_increation(self, acfactory, data, lp):
        ac1, ac2 = acfactory.get_two_online_accounts()

        c2 = ac1.create_contact(email=ac2.get_config("addr"))
        chat = ac1.create_chat_by_contact(c2)
        assert chat.id >= const.DC_CHAT_ID_LAST_SPECIAL
        wait_msgs_changed(ac1, 0, 0)  # why no chat id?

        lp.sec("create a message with a file in creation")
        orig = data.get_path("d.png")
        path = os.path.join(ac1.get_blobdir(), 'd.png')
        with open(path, "x") as fp:
            fp.write("preparing")
        prepared_original = chat.prepare_message_file(path)
        assert prepared_original.is_out_preparing()
        wait_msgs_changed(ac1, chat.id, prepared_original.id)

        lp.sec("forward the message while still in creation")
        chat2 = ac1.create_group_chat("newgroup")
        chat2.add_contact(c2)
        wait_msgs_changed(ac1, 0, 0)  # why not chat id?
        ac1.forward_messages([prepared_original], chat2)
        # XXX there might be two EVENT_MSGS_CHANGED and only one of them
        # is the one caused by forwarding
        forwarded_id = wait_msgs_changed(ac1, chat2.id)
        if forwarded_id == 0:
            forwarded_id = wait_msgs_changed(ac1, chat2.id)
            assert forwarded_id
        forwarded_msg = ac1.get_message_by_id(forwarded_id)
        assert forwarded_msg.is_out_preparing()

        lp.sec("finish creating the file and send it")
        assert prepared_original.is_out_preparing()
        shutil.copyfile(orig, path)
        chat.send_prepared(prepared_original)
        assert prepared_original.is_out_pending() or prepared_original.is_out_delivered()
        wait_msgs_changed(ac1, chat.id, prepared_original.id)

        lp.sec("expect the forwarded message to be sent now too")
        wait_msgs_changed(ac1, chat2.id, forwarded_id)
        fwd_msg = ac1.get_message_by_id(forwarded_id)
        assert fwd_msg.is_out_pending() or fwd_msg.is_out_delivered()

        lp.sec("wait for the messages to be delivered to SMTP")
        ev = ac1._evtracker.get_matching("DC_EVENT_MSG_DELIVERED")
        assert ev.data1 == chat.id
        assert ev.data2 == prepared_original.id
        ev = ac1._evtracker.get_matching("DC_EVENT_MSG_DELIVERED")
        assert ev.data1 == chat2.id
        assert ev.data2 == forwarded_id

        lp.sec("wait1 for original or forwarded messages to arrive")
        ev1 = ac2._evtracker.get_matching("DC_EVENT_MSGS_CHANGED")
        assert ev1.data1 > const.DC_CHAT_ID_LAST_SPECIAL
        received_original = ac2.get_message_by_id(ev1.data2)
        assert cmp(received_original.filename, orig, shallow=False)

        lp.sec("wait2 for original or forwarded messages to arrive")
        ev2 = ac2._evtracker.get_matching("DC_EVENT_MSGS_CHANGED")
        assert ev2.data1 > const.DC_CHAT_ID_LAST_SPECIAL
        assert ev2.data1 != ev1.data1
        received_copy = ac2.get_message_by_id(ev2.data2)
        assert cmp(received_copy.filename, orig, shallow=False)
