#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import os
import json
import math
import std_msgs.msg
import geometry_msgs.msg
import tf
from kortex_driver.msg import BaseCyclic_Feedback

import rospy
from robothon2023.full_arm_movement import FullArmMovement
from robothon2023.transform_utils import TransformUtils
from utils.kinova_pose import KinovaPose, get_kinovapose_from_pose_stamped

from utils.kinova_pose import get_kinovapose_from_list
from robothon2023.button_press_action import ButtonPressAction
from robothon2023.slider_action import SliderAction
from robothon2023.plug_remove_slid_action import PlugRemoveSlidAction
from robothon2023.probe_action import ProbeAction
from robothon2023.wind_cable_action import WindCableAction


class TaskSM(object):
    def __init__(self):
        self.board_detector_event = None
        self.init_board_pose = None
        self.board_detector_event_out = rospy.Subscriber('~board_detector_event_out', std_msgs.msg.String, self.board_detector_event_cb)
        self.board_detector_event_in = rospy.Publisher('~board_detector_event_in', std_msgs.msg.String, queue_size=1)
        self.poi_event_in = rospy.Publisher('~poi_event_in', std_msgs.msg.String, queue_size=1)
        self.init_board_pose_sub = rospy.Subscriber('~init_approximate_board_pose', geometry_msgs.msg.PoseStamped, self.board_pose_cb)
        self.perceive_board_pose = rospy.get_param("~joint_angles/perceive_board_pose")
        self.arm = FullArmMovement()
        self.tu = TransformUtils()
        self.task_order = rospy.get_param('~task_order')
        self.loop_rate = rospy.Rate(10.0)
        self.current_task_id = 0
        self.action_executors = [ButtonPressAction(self.arm, self.tu),
                                 SliderAction(self.arm, self.tu),
                                 PlugRemoveSlidAction(self.arm, self.tu),
                                 ProbeAction(self.arm, self.tu),
                                 WindCableAction(self.arm, self.tu),
                                 ButtonPressAction(self.arm, self.tu, reference_frame='red_button_link')]


    def board_pose_cb(self, msg):
        self.init_board_pose = msg

    def board_detector_event_cb(self, msg):
        self.board_detector_event = msg.data

    def run(self):
        success = self.move_arm_to_perceive_board()
        if not success:
            rospy.logerr('Moving arm to perceive board failed')
            exit(0)

        success = self.wait_for_init_board_detection()
        if not success:
            rospy.logerr('Initial Board detection failed')
            exit(0)

        self.orient_arm_to_board()
        self.poi_event_in.publish('e_start')

        success = self.wait_for_board_detection()
        if not success:
            rospy.logerr('Board detection failed')
            exit(0)

        reordered_task = False
        if len(self.task_order) == 6 and self.task_order != [0, 1, 2, 3, 4, 5]:
            reordered_task = True
            rospy.loginfo('Task order has changed!')
        for task_id in self.task_order:
            success = self.action_executors[task_id].do()
            if reordered_task:
                self.move_arm_to_perceive_board()
            if not success:
                rospy.logerr('%s action failed' % self.action_executors[task_id].__class__.__name__)
        # after we finish all tasks, move back to perceive board
        success = self.move_arm_to_perceive_board(clear_faults=False)


    def move_arm_to_perceive_board(self, clear_faults=True):
        if clear_faults:
            self.arm.clear_faults()
            self.arm.subscribe_to_a_robot_notification()
        success = False
        retries = 0
        while not success and retries < 3:
            success = self.arm.send_joint_angles(self.perceive_board_pose)
            retries += 1
        self.arm.execute_gripper_command(0.35)
        return success

    def orient_arm_to_board(self):
        euler = tf.transformations.euler_from_quaternion(
            [self.init_board_pose.pose.orientation.x,
            self.init_board_pose.pose.orientation.y,
            self.init_board_pose.pose.orientation.z,
            self.init_board_pose.pose.orientation.w]
        )
        quat = tf.transformations.quaternion_from_euler(math.pi, 0.0, euler[2])

        feedback = rospy.wait_for_message("/my_gen3/base_feedback", BaseCyclic_Feedback)
        updated_pose = self.init_board_pose
        updated_pose.pose.position.x = self.init_board_pose.pose.position.x
        updated_pose.pose.position.y = self.init_board_pose.pose.position.y
        updated_pose.pose.position.z = feedback.base.tool_pose_z - 0.05
        updated_pose.pose.orientation = geometry_msgs.msg.Quaternion(*quat)
        kinova_pose = get_kinovapose_from_pose_stamped(updated_pose)
        self.arm.send_cartesian_pose(kinova_pose)


    def wait_for_board_detection(self):
        self.board_detector_event = None
        self.board_detector_event_in.publish('e_start')
        timeout = rospy.Duration.from_sec(20.0)
        start_time = rospy.Time.now()
        while not rospy.is_shutdown():
            if self.board_detector_event == 'e_done':
                self.board_detector_event_in.publish('e_stop')
                return True
            elif self.board_detector_event == 'e_failure':
                rospy.logerr('Board detection failure')
                self.board_detector_event_in.publish('e_stop')
                return False
            if (rospy.Time.now() - start_time) > timeout:
                rospy.logerr('Board detection timeout')
                self.board_detector_event_in.publish('e_stop')
                return False
            self.loop_rate.sleep()

    def wait_for_init_board_detection(self):
        self.board_detector_event = None
        self.board_detector_event_in.publish('e_start')
        timeout = rospy.Duration.from_sec(20.0)
        start_time = rospy.Time.now()
        while not rospy.is_shutdown():
            if self.init_board_pose is not None:
                self.board_detector_event_in.publish('e_stop')
                return True
            if (rospy.Time.now() - start_time) > timeout:
                rospy.logerr('Board detection timeout')
                self.board_detector_event_in.publish('e_stop')
                return False
            self.loop_rate.sleep()



def main():
    rospy.init_node("task_sm")
    task_sm = TaskSM()
    task_sm.run()

if __name__ == "__main__":
    main()
